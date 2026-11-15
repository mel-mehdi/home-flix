// Content Loading and Pagination

let moviePage = 1;
let seriesPage = 1;
let searchQuery = '';

// Initialize pagination data
function initializePaginationData(movie_page, series_page, search_query) {
    moviePage = movie_page;
    seriesPage = series_page;
    searchQuery = search_query || '';
}

// Load more movies
function loadMoreMovies() {
    const button = document.querySelector('#movies-slider').parentElement.querySelector('.load-more-button');
    button.disabled = true;
    button.textContent = 'Loading...';
    moviePage++;
    const url = searchQuery ? `/search_more_movies/${encodeURIComponent(searchQuery)}/${moviePage}` : `/load_more_movies/${moviePage}`;
    
    fetch(url)
        .then(response => response.json())
        .then((data) => {
            if (data.movies && data.movies.length > 0) {
                const slider = document.getElementById('movies-slider');
                data.movies.forEach(movie => {
                    const card = createTitleCard(movie, 'movie');
                    slider.appendChild(card);
                });
            } else {
                button.style.display = 'none';
            }
            button.disabled = false;
            button.textContent = searchQuery ? 'Load More' : 'Load More Movies';
        })
        .catch(error => {
            console.error('Error loading more movies:', error);
            button.disabled = false;
            button.textContent = searchQuery ? 'Load More' : 'Load More Movies';
        });
}

// Show More on the Trending rows (kind: 'movie' or 'series'); hides itself when the server has no more
const trendingPages = { movie: 1, series: 1 };

function loadMoreTrending(kind, button) {
    button.disabled = true;
    button.textContent = 'Loading...';
    trendingPages[kind]++;

    fetch(`/load_more_trending/${kind}/${trendingPages[kind]}`)
        .then(response => response.json())
        .then((data) => {
            const slider = document.getElementById(kind === 'movie' ? 'trending-movies-slider' : 'trending-series-slider');
            (data.items || []).forEach(item => {
                slider.appendChild(createTitleCard(item, kind));
            });
            button.disabled = false;
            button.textContent = 'Show More';
            if (!data.has_more || !data.items || data.items.length === 0) {
                button.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Error loading more trending titles:', error);
            trendingPages[kind]--;
            button.disabled = false;
            button.textContent = 'Show More';
        });
}

// Load more series
function loadMoreSeries() {
    const button = document.querySelector('#series-slider').parentElement.querySelector('.load-more-button');
    button.disabled = true;
    button.textContent = 'Loading...';
    seriesPage++;
    const url = searchQuery ? `/search_more_series/${encodeURIComponent(searchQuery)}/${seriesPage}` : `/load_more_series/${seriesPage}`;
    
    fetch(url)
        .then(response => response.json())
        .then((data) => {
            if (data.series && data.series.length > 0) {
                const slider = document.getElementById('series-slider');
                data.series.forEach(show => {
                    const card = createTitleCard(show, 'series');
                    slider.appendChild(card);
                });
            } else {
                button.style.display = 'none';
            }
            button.disabled = false;
            button.textContent = searchQuery ? 'Load More' : 'Load More Shows';
        })
        .catch(error => {
            console.error('Error loading more series:', error);
            button.disabled = false;
            button.textContent = searchQuery ? 'Load More' : 'Load More Shows';
        });
}
