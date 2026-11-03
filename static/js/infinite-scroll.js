/**
 * Infinite Scroll for Movie Listings
 * Loads further pages of /movies automatically as you scroll, using the
 * /api/v1/movies endpoint with the same filters as the page.
 *
 * Only takes over when the list starts at page 1. A deep link such as
 * ?page=5 keeps the normal page links, so earlier pages stay reachable.
 */

(function () {
    'use strict';

    const movieGrid = document.getElementById('movie-grid');
    const meta = document.getElementById('scroll-meta');
    const template = document.getElementById('movie-card-template');
    if (!movieGrid || !meta || !template) return;

    let currentPage = parseInt(meta.dataset.page, 10);
    const totalPages = parseInt(meta.dataset.totalPages, 10);
    const excludeMature = meta.dataset.excludeMature === '1';
    const hasResults = movieGrid.querySelector('.movie-card-wrapper') !== null;

    // Deep links and empty results keep the server-rendered page links
    if (currentPage !== 1 || !hasResults || currentPage >= totalPages) return;

    const paginationWrapper = document.querySelector('.pagination-wrapper');
    if (paginationWrapper) paginationWrapper.hidden = true;

    let loading = false;
    let exhausted = false;

    // --- Sentinel element (triggers load when visible) ---
    const sentinel = document.createElement('div');
    sentinel.id = 'scroll-sentinel';
    sentinel.style.height = '1px';
    movieGrid.after(sentinel);

    // --- Skeleton row (shown while next page loads) ---
    const skeletonRow = document.createElement('div');
    skeletonRow.id = 'scroll-skeletons';
    skeletonRow.className = 'row d-none';
    skeletonRow.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 6; i++) {
        skeletonRow.insertAdjacentHTML('beforeend', `
            <div class="col-md-2 col-sm-4 col-6 mb-3">
                <div class="skeleton-card">
                    <div class="skeleton skeleton-poster"></div>
                    <div class="skeleton-card-body">
                        <div class="skeleton skeleton-title"></div>
                        <div class="skeleton skeleton-meta"></div>
                        <div class="skeleton skeleton-badge"></div>
                    </div>
                </div>
            </div>`);
    }
    sentinel.after(skeletonRow);

    // Status line, read out to screen readers as pages load
    const status = document.createElement('div');
    status.id = 'scroll-status';
    status.className = 'text-center py-4 text-muted';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    skeletonRow.after(status);

    // --- Build API query string from current page filters ---
    function buildApiUrl(page) {
        const params = new URLSearchParams(window.location.search);
        const apiParams = new URLSearchParams({
            page,
            per_page: 20,
            sort: params.get('sort') || 'popularity',
        });
        // HTML filter name -> API parameter name
        const mapping = {
            genre: 'genre',
            year: 'year',
            decade: 'decade',
            rating_min: 'min_rating',
            rating_max: 'max_rating',
            runtime_min: 'runtime_min',
            runtime_max: 'runtime_max',
            min_vote_count: 'min_vote_count',
            status: 'status',
        };
        Object.entries(mapping).forEach(([htmlName, apiName]) => {
            const value = params.get(htmlName);
            if (value) apiParams.set(apiName, value);
        });
        if (excludeMature) apiParams.set('exclude_mature', '1');
        return `/api/v1/movies?${apiParams.toString()}`;
    }

    // --- Build a card from the <template> (text set via textContent) ---
    function buildCard(movie) {
        const node = template.content.firstElementChild.cloneNode(true);
        const toggle = node.querySelector('.compare-toggle');
        toggle.dataset.movieId = movie.id;
        toggle.dataset.movieTitle = movie.title || '';
        toggle.dataset.poster = movie.poster_path || '';
        toggle.setAttribute('aria-label', `Add ${movie.title || 'movie'} to compare`);

        node.querySelector('.movie-link').href = `/movie/${movie.id}`;
        const img = node.querySelector('.movie-poster');
        if (movie.poster_path) {
            img.src = `https://image.tmdb.org/t/p/w342${movie.poster_path}`;
            img.alt = movie.title || '';
        } else {
            img.remove();
            node.querySelector('.poster-placeholder').classList.remove('d-none');
        }
        node.querySelector('.movie-title').textContent = movie.title || '';
        const year = movie.release_date ? movie.release_date.substring(0, 4) : '';
        node.querySelector('.movie-meta').textContent =
            [year, movie.runtime ? `${movie.runtime}m` : ''].filter(Boolean).join(' • ');
        node.querySelector('.movie-rating').textContent =
            movie.vote_count ? Number(movie.vote_average).toFixed(1) : 'N/A';
        return node;
    }

    function showRetry() {
        status.textContent = 'Could not load more movies. ';
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'btn btn-sm btn-outline-secondary';
        retry.textContent = 'Try again';
        retry.addEventListener('click', () => {
            status.textContent = '';
            observer.observe(sentinel);
            loadNextPage();
        });
        status.appendChild(retry);
    }

    // --- Fetch and inject next page ---
    async function loadNextPage() {
        if (loading || exhausted) return;
        loading = true;
        skeletonRow.classList.remove('d-none');
        status.textContent = 'Loading more movies…';

        // Give up after 15s on very slow connections
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 15000);

        try {
            const response = await fetch(buildApiUrl(currentPage + 1), { signal: controller.signal });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            const fragment = document.createDocumentFragment();
            (data.movies || []).forEach(movie => fragment.appendChild(buildCard(movie)));
            movieGrid.appendChild(fragment);
            if (window.syncCompareToggles) window.syncCompareToggles();

            currentPage = data.page;
            exhausted = currentPage >= data.total_pages || !(data.movies || []).length;
            status.textContent = exhausted ? "You've seen all the movies!" : '';
            if (exhausted) observer.disconnect();
        } catch (err) {
            observer.disconnect();
            showRetry();
        } finally {
            loading = false;
            clearTimeout(timeoutId);
            skeletonRow.classList.add('d-none');
        }
    }

    // --- IntersectionObserver watches the sentinel ---
    const observer = new IntersectionObserver(
        (entries) => {
            if (entries[0].isIntersecting) loadNextPage();
        },
        { rootMargin: '200px' }   // start loading 200px before sentinel is visible
    );
    observer.observe(sentinel);
})();
