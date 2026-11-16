// More Info popup for title cards and the hero banner

const PLUS_ICON = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" fill="currentColor"/></svg>';
const CHECK_ICON = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z" fill="currentColor"/></svg>';

let titleInfoRequest = 0; // Ignore responses for a popup that was closed or replaced

function getTitleInfoModal() {
    let modal = document.getElementById('titleInfoModal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'titleInfoModal';
    modal.className = 'title-info-modal';
    modal.hidden = true;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.innerHTML = `
        <div class="title-info-content">
            <button type="button" class="title-info-close" aria-label="Close">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/>
                </svg>
            </button>
            <div class="title-info-media">
                <div class="title-info-backdrop"></div>
                <div class="title-info-media-fade"></div>
                <div class="title-info-header">
                    <h2 class="title-info-title"></h2>
                    <div class="title-info-actions">
                        <a class="title-info-play btn btn-primary">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
                            Play
                        </a>
                        <button type="button" class="title-info-trailer btn btn-secondary">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M21 6.5l-4 3V7a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h12a1 1 0 001-1v-2.5l4 3v-11z" fill="currentColor"/></svg>
                            Trailer
                        </button>
                        <button type="button" class="title-info-mylist btn btn-icon"></button>
                    </div>
                </div>
            </div>
            <div class="title-info-body">
                <div class="title-info-main">
                    <div class="title-info-meta"></div>
                    <p class="title-info-tagline"></p>
                    <p class="title-info-overview"></p>
                </div>
                <div class="title-info-side">
                    <div class="title-info-cast"></div>
                    <div class="title-info-genres"></div>
                    <a class="title-info-details-link">Full details
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" fill="currentColor"/></svg>
                    </a>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    modal.addEventListener('click', event => {
        if (event.target === modal || event.target.closest('.title-info-close')) {
            closeTitleInfo();
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !modal.hidden) {
            closeTitleInfo();
        }
    });
    return modal;
}

// Label with a value, built with textContent so titles and names can't inject HTML
function titleInfoLine(label, value) {
    const line = document.createElement('div');
    const labelEl = document.createElement('span');
    labelEl.className = 'title-info-label';
    labelEl.textContent = `${label}: `;
    line.append(labelEl, value);
    return line;
}

async function openTitleInfo(type, id) {
    if (!id) return;
    // Continue Watching cards can be episodes; their id is the series' IMDB id
    const kind = type === 'movie' ? 'movie' : 'series';
    const modal = getTitleInfoModal();
    const request = ++titleInfoRequest;

    modal.classList.add('loading');
    modal.querySelector('.title-info-title').textContent = 'Loading…';
    modal.querySelector('.title-info-backdrop').style.backgroundImage = '';
    modal.querySelector('.title-info-body').style.visibility = 'hidden';
    modal.querySelector('.title-info-actions').style.visibility = 'hidden';
    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    // Don't rotate the hero banner underneath the popup
    if (typeof autoRotationInterval !== 'undefined' && autoRotationInterval) {
        clearInterval(autoRotationInterval);
        autoRotationInterval = null;
        modal.dataset.resumeRotation = 'true';
    }

    try {
        const response = await fetch(`/api/title_info/${kind}/${encodeURIComponent(id)}`);
        const data = await response.json();
        if (request !== titleInfoRequest || modal.hidden) return;
        if (!response.ok || !data.success) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        fillTitleInfo(modal, data.item);
    } catch (error) {
        if (request !== titleInfoRequest) return;
        console.error('Failed to load title info:', error);
        closeTitleInfo();
        if (typeof homeflixApp !== 'undefined') {
            homeflixApp.showNotification('Could not load the details for this title', 'error');
        }
    }
}

function fillTitleInfo(modal, item) {
    const kind = item.type;
    const pageUrl = `/${kind}/${encodeURIComponent(item.imdb_id)}`;

    modal.querySelector('.title-info-title').textContent = item.title;
    modal.querySelector('.title-info-backdrop').style.backgroundImage =
        item.backdrop_url ? `url('${item.backdrop_url}')` : (item.poster_url ? `url('${item.poster_url}')` : '');

    // Play goes straight to the player; series start at S1E1 like the series page
    modal.querySelector('.title-info-play').href = kind === 'movie'
        ? `/watch/movie/${encodeURIComponent(item.imdb_id)}`
        : `/watch/series/${encodeURIComponent(item.imdb_id)}/1/1`;
    modal.querySelector('.title-info-details-link').href = pageUrl;

    const trailerBtn = modal.querySelector('.title-info-trailer');
    trailerBtn.hidden = !item.trailer_key;
    trailerBtn.onclick = () => playTitleInfoTrailer(modal, item.trailer_key);

    const myListBtn = modal.querySelector('.title-info-mylist');
    myListBtn.dataset.added = item.in_my_list ? 'true' : 'false';
    myListBtn.innerHTML = item.in_my_list ? CHECK_ICON : PLUS_ICON;
    myListBtn.title = item.in_my_list ? 'Remove from My List' : 'Add to My List';
    myListBtn.onclick = () => {
        if (typeof homeflixApp !== 'undefined') {
            homeflixApp.toggleMyList(kind, item.imdb_id, item.tmdb_id, item.title, myListBtn);
        }
    };

    const meta = modal.querySelector('.title-info-meta');
    meta.replaceChildren();
    const metaParts = [];
    if (item.vote_average) metaParts.push(['title-info-score', `★ ${Number(item.vote_average).toFixed(1)}`]);
    if (item.year) metaParts.push(['', item.year]);
    if (item.rating) metaParts.push(['title-info-rating', item.rating]);
    if (kind === 'movie' && item.runtime) {
        metaParts.push(['', `${Math.floor(item.runtime / 60) ? Math.floor(item.runtime / 60) + 'h ' : ''}${item.runtime % 60}m`]);
    }
    if (kind === 'series' && item.number_of_seasons) {
        metaParts.push(['', `${item.number_of_seasons} Season${item.number_of_seasons === 1 ? '' : 's'}`]);
    }
    metaParts.forEach(([className, text]) => {
        const span = document.createElement('span');
        if (className) span.className = className;
        span.textContent = text;
        meta.appendChild(span);
    });

    const tagline = modal.querySelector('.title-info-tagline');
    tagline.textContent = item.tagline || '';
    tagline.hidden = !item.tagline;
    modal.querySelector('.title-info-overview').textContent = item.overview || 'No description available.';

    const cast = modal.querySelector('.title-info-cast');
    cast.replaceChildren();
    if (item.cast && item.cast.length) cast.appendChild(titleInfoLine('Cast', item.cast.join(', ')));
    const genres = modal.querySelector('.title-info-genres');
    genres.replaceChildren();
    if (item.genres && item.genres.length) genres.appendChild(titleInfoLine('Genres', item.genres.join(', ')));

    modal.classList.remove('loading');
    modal.querySelector('.title-info-body').style.visibility = '';
    modal.querySelector('.title-info-actions').style.visibility = '';
    modal.querySelector('.title-info-close').focus();
}

// Swap the backdrop for the YouTube trailer, inside the popup
function playTitleInfoTrailer(modal, key) {
    if (!key) return;
    const media = modal.querySelector('.title-info-media');
    let frame = media.querySelector('iframe');
    if (!frame) {
        frame = document.createElement('iframe');
        frame.title = 'Trailer';
        frame.allow = 'autoplay; encrypted-media; picture-in-picture';
        frame.allowFullscreen = true;
        media.appendChild(frame);
    }
    frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}?autoplay=1&rel=0`;
    media.classList.add('playing');
}

function closeTitleInfo() {
    const modal = document.getElementById('titleInfoModal');
    if (!modal || modal.hidden) return;
    titleInfoRequest++;

    // Removing the trailer iframe stops playback
    const media = modal.querySelector('.title-info-media');
    media.querySelector('iframe')?.remove();
    media.classList.remove('playing');

    modal.hidden = true;
    document.body.style.overflow = '';

    if (modal.dataset.resumeRotation === 'true') {
        delete modal.dataset.resumeRotation;
        if (typeof startAutoRotation === 'function') startAutoRotation();
    }
}
