/**
 * Infinite Scroll for Movie Listings
 * Replaces pagination on /movies with automatic loading on scroll.
 * Uses the existing /api/v1/movies endpoint.
 */

(function () {
    'use strict';

    // Only run on the movies page
    const movieGrid = document.getElementById('movie-grid');
    if (!movieGrid) return;

    // --- State ---
    let currentPage = parseInt(document.getElementById('scroll-meta').dataset.page, 10);
    const totalPages = parseInt(document.getElementById('scroll-meta').dataset.totalPages, 10);
    let loading = false;
    let exhausted = currentPage >= totalPages;

    // --- Hide server-rendered pagination ---
    const paginationWrapper = document.querySelector('.pagination-wrapper');
    if (paginationWrapper) paginationWrapper.style.display = 'none';

    // --- Sentinel element (triggers load when visible) ---
    const sentinel = document.createElement('div');
    sentinel.id = 'scroll-sentinel';
    sentinel.style.height = '1px';
    movieGrid.after(sentinel);

    // --- Spinner ---
    const spinner = document.createElement('div');
    spinner.id = 'scroll-spinner';
    spinner.className = 'd-flex justify-content-center py-4 d-none';
    spinner.innerHTML = `
        <div class="d-flex align-items-center gap-3 text-muted">
            <div class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></div>
            <span>Loading more movies&hellip;</span>
        </div>`;
    sentinel.after(spinner);

    // --- End of results message ---
    const endMsg = document.createElement('div');
    endMsg.id = 'scroll-end';
    endMsg.className = 'text-center py-4 text-muted d-none';
    endMsg.innerHTML = '<i class="bi bi-check-circle me-2"></i>You\'ve seen all the movies!';
    spinner.after(endMsg);

    // --- Build API query string from current page filters ---
    function buildApiUrl(page) {
        const params = new URLSearchParams(window.location.search);
        // Map HTML filter param names to API param names
        const sort = params.get('sort') || 'popularity';
        const apiParams = new URLSearchParams({ page, per_page: 20, sort });

        if (params.get('genre'))       apiParams.set('genre', params.get('genre'));
        if (params.get('year'))        apiParams.set('year', params.get('year'));
        if (params.get('rating_min'))  apiParams.set('min_rating', params.get('rating_min'));

        return `/api/v1/movies?${apiParams.toString()}`;
    }

    // --- Render a single movie card matching movies.html structure ---
    function buildCard(movie) {
        const year = movie.release_date ? movie.release_date.substring(0, 4) : '';
        const rating = movie.vote_average ? parseFloat(movie.vote_average).toFixed(1) : 'N/A';
        const posterUrl = movie.poster_path
            ? `https://image.tmdb.org/t/p/w300${movie.poster_path}`
            : null;

        const imgHtml = posterUrl
            ? `<img src="${posterUrl}" class="card-img-top" alt="${escapeHtml(movie.title)}" loading="lazy">`
            : `<div class="card-img-top bg-secondary d-flex align-items-center justify-content-center" style="height:450px;">
                   <i class="bi bi-film" style="font-size:3rem;color:#666;"></i>
               </div>`;

        const col = document.createElement('div');
        col.className = 'col-md-2 col-sm-4 col-6 mb-3';
        col.innerHTML = `
            <a href="/movie/${movie.id}" class="text-decoration-none">
                <div class="card movie-card h-100">
                    ${imgHtml}
                    <div class="card-body p-2">
                        <h6 class="card-title small mb-1">${escapeHtml(movie.title)}</h6>
                        <p class="card-text small text-muted mb-1">${escapeHtml(year)}</p>
                        <span class="badge bg-warning text-dark">
                            <i class="bi bi-star-fill"></i> ${rating}
                        </span>
                    </div>
                </div>
            </a>`;
        return col;
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // --- Fetch and inject next page ---
    async function loadNextPage() {
        if (loading || exhausted) return;
        loading = true;

        spinner.classList.remove('d-none');

        try {
            const nextPage = currentPage + 1;
            const url = buildApiUrl(nextPage);
            const response = await fetch(url);

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();

            // Inject cards into grid
            const fragment = document.createDocumentFragment();
            (data.movies || []).forEach(movie => fragment.appendChild(buildCard(movie)));
            movieGrid.appendChild(fragment);

            currentPage = data.page;
            exhausted = currentPage >= data.total_pages;

            if (exhausted) {
                endMsg.classList.remove('d-none');
                observer.disconnect();
            }
        } catch (err) {
            console.error('Infinite scroll fetch failed:', err);
            // On error show pagination as fallback
            if (paginationWrapper) paginationWrapper.style.display = '';
            observer.disconnect();
        } finally {
            loading = false;
            spinner.classList.add('d-none');
        }
    }

    // --- IntersectionObserver watches the sentinel ---
    const observer = new IntersectionObserver(
        (entries) => {
            if (entries[0].isIntersecting) loadNextPage();
        },
        { rootMargin: '200px' }   // start loading 200px before sentinel is visible
    );

    if (!exhausted) {
        observer.observe(sentinel);
    } else {
        endMsg.classList.remove('d-none');
    }
})();
