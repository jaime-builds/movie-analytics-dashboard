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
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    } catch (e) {
      // Storage full or blocked (some private-browsing modes): compare just
      // won't persist across pages
    }
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
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // see saveList
    }
  }

  // --- Compare bar DOM ---
  var bar = document.createElement("div");
  bar.id = "compare-bar";
  bar.className = "compare-bar";
  bar.setAttribute("role", "region");
  bar.setAttribute("aria-label", "Movies selected for comparison");
  bar.innerHTML =
    '<div class="compare-bar-inner">' +
    '<span class="compare-bar-label"><i class="bi bi-bar-chart-line me-1"></i>Compare:</span>' +
    '<div class="compare-bar-movies" id="compare-bar-movies"></div>' +
    '<div class="compare-bar-actions">' +
    '<a id="compare-now-btn" href="#" class="btn btn-primary btn-sm">' +
    '<i class="bi bi-bar-chart-line me-1"></i>Compare Now</a>' +
    '<button id="compare-clear-btn" type="button" class="btn btn-outline-light btn-sm">' +
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

      // Built with DOM calls so stored titles and poster paths stay plain text
      if (movie.poster) {
        var img = document.createElement("img");
        img.src = TMDB_IMG + movie.poster;
        img.alt = "";
        chip.appendChild(img);
      } else {
        var icon = document.createElement("i");
        icon.className = "bi bi-film";
        icon.setAttribute("aria-hidden", "true");
        icon.style.cssText = "font-size:1rem;color:#aaa;width:20px;text-align:center;";
        chip.appendChild(icon);
      }

      var titleSpan = document.createElement("span");
      titleSpan.textContent = movie.title;
      chip.appendChild(titleSpan);

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "compare-bar-movie-remove";
      remove.dataset.id = movie.id;
      remove.title = "Remove";
      remove.setAttribute("aria-label", "Remove " + movie.title + " from compare");
      remove.innerHTML = '<i class="bi bi-x" aria-hidden="true"></i>';
      chip.appendChild(remove);
      moviesContainer.appendChild(chip);
    });

    // Update compare now link
    var ids = list.map(function (m) { return "id=" + m.id; }).join("&");
    compareNowBtn.href = "/compare?" + ids;

    // Show/hide bar. Hidden also means out of the tab order (inert), and
    // the page gets bottom padding while it covers the footer.
    if (list.length >= 2) {
      bar.classList.add("visible");
      bar.inert = false;
      document.body.classList.add("compare-bar-open");
    } else {
      bar.classList.remove("visible");
      bar.inert = true;
      document.body.classList.remove("compare-bar-open");
    }

    // Sync toggle button states on page
    syncToggleButtons();
  }

  function syncToggleButtons() {
    var list = getList();
    var ids = list.map(function (m) { return m.id; });
    document.querySelectorAll(".compare-toggle").forEach(function (btn) {
      var movieId = parseInt(btn.dataset.movieId, 10);
      var selected = ids.indexOf(movieId) !== -1;
      var label = btn.querySelector(".compare-toggle-label");
      var icon = btn.querySelector("i");
      btn.classList.toggle("selected", selected);
      btn.setAttribute("aria-pressed", selected ? "true" : "false");
      btn.title = selected ? "Remove from compare" : "Add to compare";
      if (icon) {
        icon.className = selected ? "bi bi-check-lg" : (label ? "bi bi-bar-chart-line" : "bi bi-plus-lg");
      }
      if (label) {
        label.textContent = selected ? "Remove from Compare" : "Add to Compare";
      } else {
        btn.setAttribute("aria-label", (selected ? "Remove " : "Add ") +
          (btn.dataset.movieTitle || "movie") + (selected ? " from compare" : " to compare"));
      }
    });
  }
  // Cards added later (infinite scroll) call this to show their state
  window.syncCompareToggles = syncToggleButtons;

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
          if (window.showToast) {
            window.showToast("You can compare up to " + MAX_ITEMS + " movies. Remove one first.", "warning");
          }
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
