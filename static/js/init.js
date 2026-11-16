// Main initialization script

// Initialize all components on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeHeroBanner();
    // initializeHeroBannerNavigation(); // This is now called from initializeHeroBannerData() after data is loaded
    setupTitleCardInteractions();
    initializeHeroWatchButton();
    initializeHeroNavigation();
    initializeSearch();
    
    // Wait a bit for hero banner to be fully set up, then initialize button states
    setTimeout(() => {
        initializeMyListButtons();
    }, 100);

    openTabFromUrl();
});

// The nav on other pages links here with ?filter=tv|movie or ?view=new-popular|my-list
// (templates/_subpage_nav.html); open that tab, then drop the parameter from the address bar
function openTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const filter = params.get('filter');
    const view = params.get('view');
    if (!filter && !view) return;

    if (filter === 'tv' || filter === 'movie') {
        filterByType(filter);
    } else if (view === 'new-popular') {
        showNewPopular();
    } else if (view === 'my-list') {
        showMyList();
    }

    params.delete('filter');
    params.delete('view');
    const query = params.toString();
    history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : '') + window.location.hash);
}
