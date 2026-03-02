(function () {
  "use strict";

  var STORAGE_KEY = "compareList";
  var MAX_ITEMS = 4;
  var TMDB_IMG = "https://image.tmdb.org/t/p/w92";

  // --- State ---
  function getList() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function saveList(list) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  }

  function addMovie(id, title, poster) {
    var list = getList();
    if (list.find(function (m) { return m.id === id; })) return false;
    if (list.length >= MAX_ITEMS) return false;
    list.push({ id: id, title: title, poster: poster });
    saveList(list);
    return true;
  }

  function removeMovie(id) {
    var list = getList().filter(function (m) { return m.id !== id; });
    saveList(list);
  }

  function clearList() {
    localStorage.removeItem(STORAGE_KEY);
  }

  // --- Compare bar DOM ---
  var bar = document.createElement("div");
  bar.id = "compare-bar";
  bar.className = "compare-bar";
  bar.innerHTML =
    '<div class="compare-bar-inner">' +
    '<span class="compare-bar-label"><i class="bi bi-bar-chart-line me-1"></i>Compare:</span>' +
    '<div class="compare-bar-movies" id="compare-bar-movies"></div>' +
    '<div class="compare-bar-actions">' +
    '<a id="compare-now-btn" href="#" class="btn btn-primary btn-sm">' +
    '<i class="bi bi-bar-chart-line me-1"></i>Compare Now</a>' +
    '<button id="compare-clear-btn" class="btn btn-outline-light btn-sm">' +
    '<i class="bi bi-x-circle me-1"></i>Clear</button>' +
    "</div>" +
    "</div>";
  document.body.appendChild(bar);

  var moviesContainer = document.getElementById("compare-bar-movies");
  var compareNowBtn = document.getElementById("compare-now-btn");
  var clearBtn = document.getElementById("compare-clear-btn");

  function renderBar() {
    var list = getList();
    moviesContainer.innerHTML = "";

    list.forEach(function (movie) {
      var chip = document.createElement("div");
      chip.className = "compare-bar-movie";

      var posterHtml;
      if (movie.poster) {
        posterHtml = '<img src="' + TMDB_IMG + movie.poster + '" alt="">';
      } else {
        posterHtml = '<i class="bi bi-film" style="font-size:1rem;color:#aaa;width:20px;text-align:center;"></i>';
      }

      chip.innerHTML =
        posterHtml +
        "<span>" + escapeHtml(movie.title) + "</span>" +
        '<span class="compare-bar-movie-remove" data-id="' + movie.id + '" title="Remove">' +
        '<i class="bi bi-x"></i></span>';
      moviesContainer.appendChild(chip);
    });

    // Update compare now link
    var ids = list.map(function (m) { return "id=" + m.id; }).join("&");
    compareNowBtn.href = "/compare?" + ids;

    // Show/hide bar
    if (list.length >= 2) {
      bar.classList.add("visible");
    } else {
      bar.classList.remove("visible");
    }

    // Sync toggle button states on page
    syncToggleButtons();
  }

  function syncToggleButtons() {
    var list = getList();
    var ids = list.map(function (m) { return m.id; });
    document.querySelectorAll(".compare-toggle").forEach(function (btn) {
      var movieId = parseInt(btn.dataset.movieId, 10);
      if (ids.indexOf(movieId) !== -1) {
        btn.classList.add("selected");
        btn.querySelector("i").className = "bi bi-check-lg";
        btn.title = "Remove from compare";
      } else {
        btn.classList.remove("selected");
        btn.querySelector("i").className = "bi bi-plus-lg";
        btn.title = "Add to compare";
      }
    });
  }

  function escapeHtml(str) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(str || ""));
    return d.innerHTML;
  }

  // --- Event delegation for compare toggles (handles both static and dynamic cards) ---
  document.addEventListener("click", function (e) {
    // Remove chip from compare bar
    var removeBtn = e.target.closest(".compare-bar-movie-remove");
    if (removeBtn) {
      e.preventDefault();
      removeMovie(parseInt(removeBtn.dataset.id, 10));
      renderBar();
      return;
    }

    // Clear all
    if (e.target.closest("#compare-clear-btn")) {
      e.preventDefault();
      clearList();
      renderBar();
      return;
    }

    // Toggle compare on movie card
    var toggleBtn = e.target.closest(".compare-toggle");
    if (toggleBtn) {
      e.preventDefault();
      e.stopPropagation();
      var movieId = parseInt(toggleBtn.dataset.movieId, 10);
      var movieTitle = toggleBtn.dataset.movieTitle || "";
      var poster = toggleBtn.dataset.poster || "";

      var list = getList();
      var exists = list.find(function (m) { return m.id === movieId; });

      if (exists) {
        removeMovie(movieId);
      } else {
        if (list.length >= MAX_ITEMS) {
          // Visual feedback: shake
          bar.style.animation = "none";
          bar.offsetHeight; // reflow
          return;
        }
        addMovie(movieId, movieTitle, poster);
      }
      renderBar();
      return;
    }
  });

  // Initial render
  renderBar();
})();
