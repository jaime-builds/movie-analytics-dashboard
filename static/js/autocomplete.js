(function () {
  "use strict";

  var TMDB_IMG = "https://image.tmdb.org/t/p/w92";
  var MIN_CHARS = 2;
  var DEBOUNCE_MS = 300;
  var MAX_RESULTS = 6;

  var input = document.getElementById("search-input");
  var dropdown = document.getElementById("autocomplete-dropdown");

  if (!input || !dropdown) return;

  var debounceTimer = null;
  var activeIndex = -1;
  var currentResults = [];

  function debounce(fn, ms) {
    return function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(fn, ms);
    };
  }

  function closeDropdown() {
    dropdown.style.display = "none";
    dropdown.innerHTML = "";
    activeIndex = -1;
    currentResults = [];
  }

  function setActive(index) {
    var items = dropdown.querySelectorAll(".autocomplete-item");
    items.forEach(function (el, i) {
      el.classList.toggle("active", i === index);
    });
    activeIndex = index;
  }

  function renderResults(movies) {
    dropdown.innerHTML = "";
    currentResults = movies;

    if (!movies.length) {
      closeDropdown();
      return;
    }

    movies.forEach(function (movie, i) {
      var year = movie.release_date ? movie.release_date.substring(0, 4) : "";
      var rating = movie.vote_average ? parseFloat(movie.vote_average).toFixed(1) : "N/A";

      var item = document.createElement("a");
      item.href = "/movie/" + movie.id;
      item.className = "autocomplete-item d-flex align-items-center text-decoration-none";
      item.dataset.index = i;

      var posterHtml;
      if (movie.poster_path) {
        posterHtml =
          '<img src="' +
          TMDB_IMG +
          movie.poster_path +
          '" alt="" class="autocomplete-poster" loading="lazy">';
      } else {
        posterHtml =
          '<div class="autocomplete-poster autocomplete-poster-placeholder">' +
          '<i class="bi bi-film"></i>' +
          "</div>";
      }

      item.innerHTML =
        posterHtml +
        '<div class="autocomplete-info ms-2">' +
        '<div class="autocomplete-title">' +
        escapeHtml(movie.title) +
        "</div>" +
        '<div class="autocomplete-meta text-muted small">' +
        (year ? year + " &nbsp;·&nbsp; " : "") +
        '<i class="bi bi-star-fill text-warning" style="font-size:0.7rem"></i> ' +
        rating +
        "</div>" +
        "</div>";

      item.addEventListener("mousedown", function (e) {
        // mousedown fires before blur; prevent blur from closing before click
        e.preventDefault();
      });

      item.addEventListener("click", function () {
        window.location.href = "/movie/" + movie.id;
      });

      dropdown.appendChild(item);
    });

    dropdown.style.display = "block";
    activeIndex = -1;
  }

  function escapeHtml(str) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function fetchSuggestions() {
    var q = input.value.trim();
    if (q.length < MIN_CHARS) {
      closeDropdown();
      return;
    }

    fetch("/api/v1/movies/search?q=" + encodeURIComponent(q) + "&per_page=" + MAX_RESULTS)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (input.value.trim() !== q) return; // stale response
        renderResults(data.movies || []);
      })
      .catch(function () {
        closeDropdown();
      });
  }

  var debouncedFetch = debounce(fetchSuggestions, DEBOUNCE_MS);

  input.addEventListener("input", debouncedFetch);

  input.addEventListener("keydown", function (e) {
    var items = dropdown.querySelectorAll(".autocomplete-item");
    if (!items.length) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(Math.min(activeIndex + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(Math.max(activeIndex - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      if (currentResults[activeIndex]) {
        window.location.href = "/movie/" + currentResults[activeIndex].id;
      }
    } else if (e.key === "Escape") {
      closeDropdown();
      input.blur();
    }
  });

  input.addEventListener("blur", function () {
    // Small delay lets mousedown on item fire first
    setTimeout(closeDropdown, 150);
  });

  document.addEventListener("click", function (e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      closeDropdown();
    }
  });
})();
