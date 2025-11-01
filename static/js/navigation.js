// Navigation functionality

// Mobile menu toggle
function toggleMobileMenu() {
    const mobileMenu = document.getElementById('mobileNavMenu');
    const menuToggle = document.getElementById('mobileMenuToggle');
    
    if (mobileMenu) {
        mobileMenu.classList.toggle('active');
        
        // Update icon
        const isActive = mobileMenu.classList.contains('active');
        menuToggle.innerHTML = isActive 
            ? '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/></svg>'
            : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" fill="currentColor"/></svg>';
    }
}

// Close mobile menu when clicking outside
document.addEventListener('click', function(event) {
    const mobileMenu = document.getElementById('mobileNavMenu');
    const menuToggle = document.getElementById('mobileMenuToggle');
    
    if (mobileMenu && menuToggle) {
        if (!mobileMenu.contains(event.target) && !menuToggle.contains(event.target)) {
            if (mobileMenu.classList.contains('active')) {
                toggleMobileMenu();
            }
        }
    }
});

// Close mobile menu on scroll
let lastScrollTop = 0;
window.addEventListener('scroll', function() {
    const mobileMenu = document.getElementById('mobileNavMenu');
    if (mobileMenu && mobileMenu.classList.contains('active')) {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        if (Math.abs(scrollTop - lastScrollTop) > 50) {
            toggleMobileMenu();
        }
        lastScrollTop = scrollTop;
    }
});

let currentFilter = 'all'; // Track current filter state
let currentGenreFilter = 'all'; // Track current genre filter
let currentPage = 1; // Track current page for pagination
let currentGenre = null; // Track current genre name
let currentType = null; // Track current type (movie/series)

// Genre dropdown toggle
function selectGenre(genre, displayText) {
    // Update the trigger button text (if it exists)
    const genreLabel = document.getElementById('genreListLabel');
    if (genreLabel) {
        genreLabel.textContent = displayText;
    }
    
    // Fallback for old ID if it exists
    const oldLabel = document.getElementById('currentGenreText');
    if (oldLabel) {
        oldLabel.textContent = displayText;
    }
    
    // Update active state
    const allGenreItems = document.querySelectorAll('.genre-item');
    allGenreItems.forEach(item => item.classList.remove('active'));
    event.target.classList.add('active');
    
    // Apply the filter
    filterByGenre(genre);
}

function filterByType(type) {
    currentFilter = type;
    
    // Reset genre filter when changing type filter
    currentGenreFilter = 'all';
    updateActiveGenreChip('all');
    
    // Update active state on nav links
    updateActiveNavLink(type);
    
    // Get all content rows
    const allRows = document.querySelectorAll('.content-row');
    
    if (type === 'all') {
        // Remove filtered container if it exists
        const filteredContainer = document.querySelector('.filtered-content-row');
        if (filteredContainer) {
            filteredContainer.remove();
        }
        
        // Show all content normally
        allRows.forEach(row => {
            row.style.display = 'block';
            row.classList.remove('filtered-view');
            const cards = row.querySelectorAll('.title-card');
            cards.forEach(card => {
                card.style.display = '';
            });
        });
        
        // Remove filter indicator
        removeFilterIndicator();
        
        // Scroll to top of content
        const firstRow = document.querySelector('.content-row');
        if (firstRow) {
            firstRow.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } else if (type === 'movie' || type === 'tv') {
        // Fetch from database
        fetchFilteredContent(type);
    }
}

function filterByGenre(genre) {
    currentGenreFilter = genre;
    currentGenre = genre;
    currentPage = 1; // Reset page when changing genre
    
    updateActiveGenreChip(genre);
    
    if (genre === 'all') {
        // Reset to showing all content
        filterByType('all');
        removeGenreFilterIndicator();
        return;
    }
    
    // Fetch content by genre from both movies and series
    fetchGenreFilteredContent(genre, currentPage);
}

function updateActiveNavLink(type) {
    // Remove active class from all nav links
    const allNavLinks = document.querySelectorAll('.nav-link');
    allNavLinks.forEach(link => {
        link.classList.remove('active');
    });
    
    // Add active class to current filter
    if (type === 'all') {
        const homeLinks = document.querySelectorAll('.nav-link[onclick*="filterByType(\'all\')"]');
        homeLinks.forEach(link => link.classList.add('active'));
    } else if (type === 'movie') {
        const movieLinks = document.querySelectorAll('.nav-link[onclick*="filterByType(\'movie\')"]');
        movieLinks.forEach(link => link.classList.add('active'));
    } else if (type === 'tv') {
        const tvLinks = document.querySelectorAll('.nav-link[onclick*="filterByType(\'tv\')"]');
        tvLinks.forEach(link => link.classList.add('active'));
    }
}

function showNewPopular() {
    // Show all content and highlight as "New & Popular"
    const allSections = document.querySelectorAll('.content-row');
    allSections.forEach(section => {
        section.style.display = 'block';
        const title = section.querySelector('.row-title');
        if (title.textContent.includes('Movies')) {
            title.textContent = 'New & Popular Movies';
        } else if (title.textContent.includes('TV')) {
            title.textContent = 'New & Popular TV Shows';
        }
    });
    
    // Scroll to top of content
    document.querySelector('.content-row').scrollIntoView({ behavior: 'smooth' });
}

function addFilterIndicator(filterType) {
    // Remove existing indicator if present
    removeFilterIndicator();
    
    // Create filter indicator
    const indicator = document.createElement('div');
    indicator.id = 'filter-indicator';
    indicator.className = 'filter-indicator';
    indicator.innerHTML = `
        <div class="filter-indicator-content">
            <span class="filter-indicator-text">Showing: ${filterType}</span>
            <button class="filter-indicator-close" onclick="filterByType('all')">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/>
                </svg>
            </button>
        </div>
    `;
    
    // Insert after hero banner
    const heroBanner = document.querySelector('.hero-banner');
    if (heroBanner && heroBanner.nextSibling) {
        heroBanner.parentNode.insertBefore(indicator, heroBanner.nextSibling);
    } else if (heroBanner) {
        heroBanner.parentNode.appendChild(indicator);
    } else {
        // If no hero banner, insert at the beginning of main content
        const mainContent = document.querySelector('.main-content');
        if (mainContent && mainContent.firstChild) {
            mainContent.insertBefore(indicator, mainContent.firstChild);
        }
    }
}

function removeFilterIndicator() {
    const existingIndicator = document.getElementById('filter-indicator');
    if (existingIndicator) {
        existingIndicator.remove();
    }
}

function updateActiveGenreChip(genre) {
    const allItems = document.querySelectorAll('.genre-item');
    allItems.forEach(item => {
        item.classList.remove('active');
    });
    
    // Find and activate the matching item
    allItems.forEach(item => {
        const itemText = item.textContent.trim().replace('✓ ', '');
        if ((genre === 'all' && itemText === 'All Genres') || itemText === genre) {
            item.classList.add('active');
        }
    });
    
    // Update dropdown trigger text
    const triggerText = document.getElementById('currentGenreText');
    if (triggerText) {
        if (genre === 'all') {
            triggerText.textContent = 'Genres';
        } else {
            triggerText.textContent = genre;
        }
    }
}

function addGenreFilterIndicator(genre) {
    removeGenreFilterIndicator();
    
    const indicator = document.createElement('div');
    indicator.id = 'genre-filter-indicator';
    indicator.className = 'filter-indicator';
    indicator.innerHTML = `
        <div class="filter-indicator-content">
            <span class="filter-indicator-text">Genre: ${genre}</span>
            <button class="filter-indicator-close" onclick="filterByGenre('all')">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/>
                </svg>
            </button>
        </div>
    `;
    
    const genreBar = document.getElementById('genreFilterBar');
    if (genreBar && genreBar.nextSibling) {
        genreBar.parentNode.insertBefore(indicator, genreBar.nextSibling);
    }
}

function removeGenreFilterIndicator() {
    const indicator = document.getElementById('genre-filter-indicator');
    if (indicator) {
        indicator.remove();
    }
}

// Fetch filtered content from database
async function fetchFilteredContent(type) {
    const targetType = type === 'movie' ? 'movie' : 'series';
    const filterLabel = type === 'movie' ? 'Movies' : 'TV Shows';
    
    // Reset pagination
    currentPage = 1;
    currentType = targetType;
    currentGenre = null;
    
    // Show loading indicator
    showLoadingIndicator(`Loading ${filterLabel}...`);
    
    try {
        // Make API call to get filtered data
        const response = await fetch(`/api/filter?type=${targetType}&page=${currentPage}&limit=16`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Create or get filtered view container
        let filteredContainer = document.querySelector('.filtered-content-row');
        
        if (!filteredContainer) {
            // Create new filtered container
            filteredContainer = document.createElement('section');
            filteredContainer.className = 'content-row filtered-content-row';
            filteredContainer.innerHTML = `
                <div class="row-header">
                    <h2 class="row-title" id="filtered-row-title"></h2>
                </div>
                <div class="row-slider">
                    <div class="slider-container filtered-grid" id="filtered-slider"></div>
                </div>
                <div id="load-more-container" style="display: none;"></div>
            `;
            
            // Insert after hero banner
            const heroBanner = document.querySelector('.hero-banner');
            if (heroBanner && heroBanner.nextSibling) {
                heroBanner.parentNode.insertBefore(filteredContainer, heroBanner.nextSibling);
            }
        }
        
        // Hide all original rows
        const allRows = document.querySelectorAll('.content-row');
        allRows.forEach(row => {
            if (!row.classList.contains('filtered-content-row')) {
                row.style.display = 'none';
            }
        });
        
        // Show filtered container
        filteredContainer.style.display = 'block';
        
        // Update title
        const titleElement = document.getElementById('filtered-row-title');
        if (titleElement) {
            titleElement.textContent = `${filterLabel} (${data.items.length} items)`;
        }
        
        // Clear and populate filtered slider
        const filteredSlider = document.getElementById('filtered-slider');
        if (filteredSlider) {
            filteredSlider.innerHTML = '';
            
            // Create cards from API data
            data.items.forEach(item => {
                const card = createTitleCard(item);
                filteredSlider.appendChild(card);
            });
        }
        
        // Remove loading indicator
        removeLoadingIndicator();
        
        // Add filter indicator
        addFilterIndicator(`${filterLabel} - Showing ${data.items.length} of ${data.total} total`);
        
        // Scroll to filtered section
        setTimeout(() => {
            filteredContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
        
    } catch (error) {
        console.error('Error fetching filtered content:', error);
        removeLoadingIndicator();
        showErrorMessage(`Failed to load ${filterLabel}. Please try again.`);
    }
}

// Fetch genre-filtered content from database
async function fetchGenreFilteredContent(genre, page = 1, append = false) {
    currentGenre = genre;
    
    if (!append) {
        currentPage = 1;
        showLoadingIndicator(`Loading ${genre} content...`);
    } else {
        // Show loading on the button
        const loadMoreBtn = document.getElementById('load-more-btn');
        if (loadMoreBtn) {
            loadMoreBtn.disabled = true;
            loadMoreBtn.innerHTML = '<div class="loading-spinner small"></div> Loading...';
        }
    }
    
    try {
        // Fetch both movies and series with this genre
        const movieResponse = await fetch(`/api/filter?type=movie&genre=${encodeURIComponent(genre)}&page=${page}&limit=16`);
        const seriesResponse = await fetch(`/api/filter?type=series&genre=${encodeURIComponent(genre)}&page=${page}&limit=16`);
        
        if (!movieResponse.ok || !seriesResponse.ok) {
            throw new Error('Failed to fetch genre content');
        }
        
        const movieData = await movieResponse.json();
        const seriesData = await seriesResponse.json();
        
        // Combine and sort by popularity (if available)
        const allItems = [...movieData.items, ...seriesData.items];
        const totalCount = movieData.total + seriesData.total;
        const hasMore = movieData.has_more || seriesData.has_more;
        
        // Create or get filtered view container
        let filteredContainer = document.querySelector('.filtered-content-row');
        
        if (!filteredContainer || !append) {
            // Remove existing container if not appending
            if (filteredContainer && !append) {
                filteredContainer.remove();
            }
            
            // Create new filtered container
            filteredContainer = document.createElement('section');
            filteredContainer.className = 'content-row filtered-content-row';
            filteredContainer.innerHTML = `
                <div class="row-header">
                    <h2 class="row-title" id="filtered-row-title"></h2>
                </div>
                <div class="row-slider">
                    <div class="slider-container filtered-grid" id="filtered-slider"></div>
                </div>
                <div id="load-more-container"></div>
            `;
            
            // Insert after hero banner
            const heroBanner = document.querySelector('.hero-banner');
            if (heroBanner && heroBanner.nextSibling) {
                heroBanner.parentNode.insertBefore(filteredContainer, heroBanner.nextSibling);
            }
        }
        
        // Hide all original rows
        const allRows = document.querySelectorAll('.content-row');
        allRows.forEach(row => {
            if (!row.classList.contains('filtered-content-row')) {
                row.style.display = 'none';
            }
        });
        
        // Show filtered container
        filteredContainer.style.display = 'block';
        
        // Update title
        const titleElement = document.getElementById('filtered-row-title');
        if (titleElement) {
            const currentCount = append ? 
                document.querySelectorAll('#filtered-slider .title-card').length + allItems.length : 
                allItems.length;
            titleElement.textContent = `${genre} (${currentCount} of ${totalCount})`;
        }
        
        // Get or clear filtered slider
        const filteredSlider = document.getElementById('filtered-slider');
        if (filteredSlider) {
            if (!append) {
                filteredSlider.innerHTML = '';
            }
            
            // Create cards from API data
            allItems.forEach(item => {
                const card = createTitleCard(item);
                filteredSlider.appendChild(card);
            });
        }
        
        // Add or update "Load More" button
        const loadMoreContainer = document.getElementById('load-more-container');
        if (loadMoreContainer) {
            if (hasMore && allItems.length > 0) {
                loadMoreContainer.innerHTML = `
                    <button id="load-more-btn" class="load-more-button" onclick="loadMoreGenreContent()">
                        Load More
                    </button>
                `;
                loadMoreContainer.style.display = 'block';
            } else {
                loadMoreContainer.style.display = 'none';
            }
        }
        
        // Remove loading indicator
        removeLoadingIndicator();
        
        // Add genre filter indicator
        addGenreFilterIndicator(genre);
        
        // Scroll to filtered section (only if not appending)
        if (!append) {
            setTimeout(() => {
                filteredContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        }
        
    } catch (error) {
        console.error('Error fetching genre content:', error);
        removeLoadingIndicator();
        showErrorMessage(`Failed to load ${genre} content. Please try again.`);
    }
}

// Load more content for current genre
function loadMoreGenreContent() {
    if (!currentGenre || currentGenre === 'all') return;
    
    currentPage++;
    fetchGenreFilteredContent(currentGenre, currentPage, true);
}

// Create title card from item data
function createTitleCard(item) {
    const card = document.createElement('div');
    card.className = 'title-card';
    card.dataset.title = item.title;
    card.dataset.type = item.type;
    card.dataset.id = item.imdb_id || item.id;
    card.dataset.tmdbId = item.tmdb_id || '';
    card.dataset.genres = item.genres ? item.genres.join(',') : '';
    
    const posterUrl = item.poster_url || '';
    const posterHTML = posterUrl 
        ? `<img src="${posterUrl}" alt="${item.title}" loading="lazy">`
        : `<div class="placeholder-image"><span>${item.title.charAt(0)}</span></div>`;
    
    card.innerHTML = `
        <div class="title-card-image">
            ${posterHTML}
        </div>
        <div class="title-card-metadata">
            <div class="metadata-top">
                <div class="title-card-play-button">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8 5v14l11-7z" fill="currentColor"/>
                    </svg>
                </div>
                <div class="title-card-add-button">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" fill="currentColor"/>
                    </svg>
                </div>
                <div class="title-card-like-button">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" fill="currentColor"/>
                    </svg>
                </div>
                <div class="title-card-expand-button">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6z" fill="currentColor"/>
                    </svg>
                </div>
            </div>
            <div class="metadata-bottom">
                <div class="title-card-title">${item.title}</div>
                <div class="title-card-genres">
                    <span class="genre-tag">${item.quality || (item.type === 'series' ? 'Series' : 'HD')}</span>
                </div>
            </div>
        </div>
    `;
    
    return card;
}

// Show loading indicator
function showLoadingIndicator(message) {
    removeLoadingIndicator();
    
    const indicator = document.createElement('div');
    indicator.id = 'loading-indicator';
    indicator.className = 'filter-indicator loading';
    indicator.innerHTML = `
        <div class="filter-indicator-content">
            <span class="filter-indicator-text">${message}</span>
            <div class="loading-spinner"></div>
        </div>
    `;
    
    const heroBanner = document.querySelector('.hero-banner');
    if (heroBanner && heroBanner.nextSibling) {
        heroBanner.parentNode.insertBefore(indicator, heroBanner.nextSibling);
    }
}

// Remove loading indicator
function removeLoadingIndicator() {
    const indicator = document.getElementById('loading-indicator');
    if (indicator) {
        indicator.remove();
    }
}

// Show error message
function showErrorMessage(message) {
    const indicator = document.createElement('div');
    indicator.className = 'filter-indicator error';
    indicator.innerHTML = `
        <div class="filter-indicator-content">
            <span class="filter-indicator-text">${message}</span>
            <button class="filter-indicator-close" onclick="this.parentElement.parentElement.remove()">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor"/>
                </svg>
            </button>
        </div>
    `;
    
    const heroBanner = document.querySelector('.hero-banner');
    if (heroBanner && heroBanner.nextSibling) {
        heroBanner.parentNode.insertBefore(indicator, heroBanner.nextSibling);
    }
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (indicator.parentNode) {
            indicator.remove();
        }
    }, 5000);
}
