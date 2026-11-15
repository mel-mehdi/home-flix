// My List Functionality

// Navigation functionality for detail pages
function filterByType(type) {
    window.location.href = '/?filter=' + type;
}

function showNewPopular() {
    window.location.href = '/?view=new-popular';
}

// Initialize My List button states
async function initializeMyListButtons() {
    try {
        const response = await fetch('/api/my-list');
        const data = await response.json();
        
        if (data.success && data.items) {
            const myListIds = new Set(data.items.map(item => item.id || item.imdb_id));
            
            // Update all add buttons in title cards
            document.querySelectorAll('.title-card').forEach(card => {
                const id = card.dataset.id;
                const addButton = card.querySelector('.title-card-add-button');
                
                if (addButton && myListIds.has(id)) {
                    addButton.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z" fill="currentColor"/></svg>';
                    addButton.dataset.added = 'true';
                    addButton.title = 'Remove from My List';
                }
            });
            
            // Also update hero button if it exists
            const heroAddBtn = document.getElementById('heroAddBtn');
            if (heroAddBtn) {
                const heroData = document.querySelector('[data-hero="true"]');
                if (heroData) {
                    const heroId = heroData.dataset.id;
                    if (myListIds.has(heroId)) {
                        heroAddBtn.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z" fill="currentColor"/></svg>';
                        heroAddBtn.dataset.added = 'true';
                        heroAddBtn.title = 'Remove from My List';
                    }
                }
            }
        }
    } catch (error) {
        console.error('Failed to initialize My List buttons:', error);
    }
}

function showMyList() {
    // Fetch My List items from API
    fetch('/api/my-list')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.items && data.items.length > 0) {
                openMyListModal(data.items);
            } else {
                // No items in My List
                if (typeof homeflixApp !== 'undefined') {
                    homeflixApp.showNotification('Your list is empty! Click the + button on any movie or show to add it to your list.', 'info');
                }
            }
        })
        .catch(error => {
            console.error('Error fetching My List:', error);
            if (typeof homeflixApp !== 'undefined') {
                homeflixApp.showNotification('Failed to load My List', 'error');
            }
        });
}

// Escape text for use inside the popup's HTML (titles can contain quotes and <, >, &)
function escapeMyListText(text) {
    const span = document.createElement('span');
    span.textContent = text == null ? '' : String(text);
    return span.innerHTML.replace(/"/g, '&quot;');
}

function openMyListModal(items) {
    // Create modal overlay
    const modal = document.createElement('div');
    modal.className = 'my-list-modal';
    modal.innerHTML = `
        <div class="my-list-modal-content">
            <div class="my-list-modal-header">
                <h2>My List <span class="my-list-count">${items.length}</span></h2>
                <button class="my-list-modal-close" onclick="closeMyListModal()" aria-label="Close">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/>
                    </svg>
                </button>
            </div>
            <div class="my-list-modal-body">
                <!-- Every item in one row that scrolls left to right -->
                <button class="my-list-scroll my-list-scroll-prev" aria-label="Scroll left">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z" fill="currentColor"/></svg>
                </button>
                <div class="my-list-grid">
                    ${items.map(item => {
                        const id = escapeMyListText(item.id || item.imdb_id);
                        const title = escapeMyListText(item.title);
                        const type = escapeMyListText(item.type);
                        return `
                        <div class="my-list-item" data-type="${type}" data-id="${id}" data-tmdb-id="${escapeMyListText(item.tmdb_id)}" data-title="${title}">
                            <div class="my-list-item-poster">
                                ${item.poster_url ? `<img src="${escapeMyListText(item.poster_url)}" alt="${title}" loading="lazy">` : `<div class="placeholder-image"><span>${escapeMyListText((item.title || '?').charAt(0))}</span></div>`}
                                <div class="my-list-item-overlay">
                                    <button class="btn btn-primary my-list-play">
                                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <path d="M8 5v14l11-7z" fill="currentColor"/>
                                        </svg>
                                        Play
                                    </button>
                                    <button class="btn btn-icon my-list-remove" title="Remove from My List">
                                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z" fill="currentColor"/>
                                        </svg>
                                    </button>
                                </div>
                            </div>
                            <div class="my-list-item-info">
                                <h3>${title}</h3>
                                <p class="my-list-item-type">${item.type === 'movie' ? 'Movie' : 'TV Show'}</p>
                            </div>
                        </div>
                    `;
                    }).join('')}
                </div>
                <button class="my-list-scroll my-list-scroll-next" aria-label="Scroll right">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" fill="currentColor"/></svg>
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    const row = modal.querySelector('.my-list-grid');
    const prevButton = modal.querySelector('.my-list-scroll-prev');
    const nextButton = modal.querySelector('.my-list-scroll-next');
    
    // Arrows only where there is more to see in that direction
    function updateScrollButtons() {
        const maxScroll = row.scrollWidth - row.clientWidth;
        prevButton.hidden = row.scrollLeft <= 4;
        nextButton.hidden = row.scrollLeft >= maxScroll - 4;
    }
    prevButton.addEventListener('click', () => row.scrollBy({ left: -row.clientWidth * 0.8, behavior: 'smooth' }));
    nextButton.addEventListener('click', () => row.scrollBy({ left: row.clientWidth * 0.8, behavior: 'smooth' }));
    row.addEventListener('scroll', updateScrollButtons, { passive: true });
    window.addEventListener('resize', updateScrollButtons);
    
    // A regular mouse wheel scrolls the row sideways
    row.addEventListener('wheel', function(e) {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && row.scrollWidth > row.clientWidth) {
            e.preventDefault();
            row.scrollLeft += e.deltaY;
        }
    }, { passive: false });
    
    // Play and remove buttons read the item's data attributes, so titles need no quoting
    row.addEventListener('click', function(e) {
        const item = e.target.closest('.my-list-item');
        if (!item) return;
        if (e.target.closest('.my-list-remove')) {
            removeFromMyListModal(item.dataset.type, item.dataset.id, item.dataset.title);
        } else if (e.target.closest('.my-list-play') && typeof homeflixApp !== 'undefined') {
            homeflixApp.playTitle(item.dataset.type, item.dataset.id);
        }
    });
    
    // Add animation
    setTimeout(() => {
        modal.classList.add('active');
        updateScrollButtons();
    }, 10);
    
    // Close on outside click
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeMyListModal();
        }
    });
}

function closeMyListModal() {
    const modal = document.querySelector('.my-list-modal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => {
            modal.remove();
        }, 300);
    }
}

function removeFromMyListModal(type, id, title) {
    fetch('/api/my-list', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            action: 'remove',
            type: type,
            id: id,
            title: title
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof homeflixApp !== 'undefined') {
                homeflixApp.showNotification(`Removed "${title}" from My List`, 'info');
            }
            
            // Remove the item from modal
            const itemElement = document.querySelector(`.my-list-item[data-id="${id}"]`);
            if (itemElement) {
                itemElement.style.animation = 'fadeOut 0.3s ease';
                setTimeout(() => {
                    itemElement.remove();

                    // Check if modal is now empty
                    const remainingItems = document.querySelectorAll('.my-list-item');
                    const count = document.querySelector('.my-list-count');
                    if (count) count.textContent = remainingItems.length;
                    if (remainingItems.length === 0) {
                        closeMyListModal();
                        if (typeof homeflixApp !== 'undefined') {
                            homeflixApp.showNotification('Your list is now empty', 'info');
                        }
                    }
                }, 300);
            }
        }
    })
    .catch(error => {
        if (typeof homeflixApp !== 'undefined') {
            homeflixApp.showNotification('Failed to remove from My List', 'error');
        }
    });
}

// Add to My List functionality - handles both title cards and detail pages
async function addToMyList(...args) {
    let type, id, tmdbId, title, button;
    
    if (args.length === 2) {
        // Called from title card: addToMyList(title, button)
        [title, button] = args;
        const card = button.closest('.title-card');
        if (!card) {
            console.error('Could not find title card element');
            return;
        }
        type = card.dataset.type;
        id = card.dataset.id;
        tmdbId = card.dataset.tmdbId;
    } else if (args.length === 5) {
        // Called from details page: addToMyList(type, id, tmdbId, title, button)
        [type, id, tmdbId, title, button] = args;
    } else {
        console.error('Invalid arguments for addToMyList');
        return;
    }
    
    try {
        const isAdded = button.getAttribute('data-added') === 'true';
        const action = isAdded ? 'remove' : 'add';
        
        const response = await fetch('/api/my-list', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: action,
                type: type,
                id: id,
                tmdb_id: tmdbId,
                title: title
            })
        });

        if (response.ok) {
            if (action === 'add') {
                // Added to list - show checkmark icon
                button.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z" fill="currentColor"/></svg>';
                button.setAttribute('data-added', 'true');
                button.title = 'Remove from My List';
            } else {
                // Removed from list - show plus icon
                button.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" fill="currentColor"/></svg>';
                button.setAttribute('data-added', 'false');
                button.title = 'Add to My List';
            }
        }
    } catch (error) {
        console.error('Failed to update My List:', error);
    }
}

// Initialize My List buttons on detail pages
function initializeDetailPageButtons() {
    console.log('Initializing detail page My List buttons...');
    const myListButtons = document.querySelectorAll('.btn-add-list[data-type]');
    console.log('Found buttons:', myListButtons.length);
    
    myListButtons.forEach((button, index) => {
        console.log(`Setting up button ${index}:`, {
            type: button.getAttribute('data-type'),
            id: button.getAttribute('data-id'),
            title: button.getAttribute('data-title')
        });
        
        // Remove any existing click listeners by cloning
        const newButton = button.cloneNode(true);
        button.parentNode.replaceChild(newButton, button);
        
        // Add new click listener
        newButton.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            console.log('My List button clicked!');
            
            const type = this.getAttribute('data-type');
            const id = this.getAttribute('data-id');
            const tmdbId = this.getAttribute('data-tmdb-id');
            const title = this.getAttribute('data-title');
            
            console.log('Adding to list:', { type, id, tmdbId, title });
            
            addToMyList(type, id, tmdbId, title, this);
        });
    });
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeDetailPageButtons);
} else {
    initializeDetailPageButtons();
}
