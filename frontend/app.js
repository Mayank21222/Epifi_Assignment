const API_BASE = "/api";
const POLL_INTERVAL_MS = 5000;

const form = document.getElementById("add-url-form");
const urlInput = document.getElementById("url-input");
const nameInput = document.getElementById("name-input");
const formError = document.getElementById("form-error");
const urlsContainer = document.getElementById("urls-container");
const loadingEl = document.getElementById("loading");
const connectionError = document.getElementById("connection-error");
const emptyEl = document.getElementById("empty-state");

let lastFetchFailed = false;

async function fetchUrls() {
  const res = await fetch(`${API_BASE}/urls`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function addUrl(url, name) {
  const res = await fetch(`${API_BASE}/urls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, name }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function deleteUrl(id) {
  const res = await fetch(`${API_BASE}/urls/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function updateUrl(id, data) {
  const res = await fetch(`${API_BASE}/urls/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

function renderUrls(urls) {
  loadingEl.classList.add("hidden");
  connectionError.classList.add("hidden");
  lastFetchFailed = false;

  if (!urls.length) {
    emptyEl.classList.remove("hidden");
    urlsContainer.innerHTML = "";
    return;
  }

  emptyEl.classList.add("hidden");

  urlsContainer.innerHTML = urls
    .map((u) => {
      const check = u.latest_check;
      let statusClass = "pending";
      let statusLabel = "Pending";
      let responseInfo = "No data yet";
      let errorInfo = "";

      if (check) {
        if (check.is_up) {
          statusClass = "up";
          statusLabel = "Up";
        } else {
          statusClass = "down";
          statusLabel = "Down";
        }
        responseInfo = `${check.response_time_ms ?? "?"} ms`;
        if (check.error_message) {
          errorInfo = ` — ${escapeHtml(check.error_message)}`;
        }
      }

      return `
        <div class="url-card ${statusClass}" data-id="${u.id}">
          <div class="url-info">
            <div class="url-name">
              <span class="name-display">${escapeHtml(u.name || u.url)}</span>
              <span class="name-edit hidden">
                <input type="text" class="name-input" value="${escapeHtml(u.name || u.url)}">
                <button class="save-name-btn">Save</button>
                <button class="cancel-name-btn">Cancel</button>
              </span>
            </div>
            <a href="${escapeHtml(u.url)}" target="_blank" rel="noopener" class="url-link">${escapeHtml(u.url)}</a>
            <div class="url-meta">
              <span class="status-badge ${statusClass}">${statusLabel}</span>
              <span>Response: ${responseInfo}</span>
              ${errorInfo ? `<span class="error">${errorInfo}</span>` : ""}
            </div>
          </div>
          <div class="url-actions">
            <button class="edit-name-btn">Rename</button>
            <button class="delete-btn">Remove</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function showConnectionError() {
  loadingEl.classList.add("hidden");
  emptyEl.classList.add("hidden");
  urlsContainer.innerHTML = "";
  connectionError.classList.remove("hidden");
  lastFetchFailed = true;
}

async function refresh() {
  try {
    const urls = await fetchUrls();
    renderUrls(urls);
  } catch {
    showConnectionError();
  }
}

function startPolling() {
  refresh();
  setInterval(refresh, POLL_INTERVAL_MS);
}

// Form submit
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.classList.add("hidden");
  const url = urlInput.value.trim();
  const name = nameInput.value.trim() || url;
  if (!url) return;

  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = "Adding...";

  try {
    await addUrl(url, name);
    urlInput.value = "";
    nameInput.value = "";
    await refresh();
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove("hidden");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Monitor";
  }
});

// Event delegation for card actions
urlsContainer.addEventListener("click", async (e) => {
  const card = e.target.closest(".url-card");
  if (!card) return;
  const id = Number(card.dataset.id);

  // Delete
  if (e.target.classList.contains("delete-btn")) {
    e.target.disabled = true;
    e.target.textContent = "Removing...";
    try {
      await deleteUrl(id);
      refresh();
    } catch {
      e.target.disabled = false;
      e.target.textContent = "Remove";
    }
    return;
  }

  // Edit name button
  if (e.target.classList.contains("edit-name-btn")) {
    card.querySelector(".name-display").classList.add("hidden");
    card.querySelector(".name-edit").classList.remove("hidden");
    card.querySelector(".name-input").focus();
    return;
  }

  // Save name
  if (e.target.classList.contains("save-name-btn")) {
    const input = card.querySelector(".name-input");
    const newName = input.value.trim();
    if (!newName) return;
    try {
      await updateUrl(id, { name: newName });
      refresh();
    } catch (err) {
      formError.textContent = err.message;
      formError.classList.remove("hidden");
    }
    return;
  }

  // Cancel edit
  if (e.target.classList.contains("cancel-name-btn")) {
    card.querySelector(".name-display").classList.remove("hidden");
    card.querySelector(".name-edit").classList.add("hidden");
    return;
  }
});

// Enter key to save name edit
urlsContainer.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.classList.contains("name-input")) {
    e.target.closest(".url-card").querySelector(".save-name-btn").click();
  }
  if (e.key === "Escape" && e.target.classList.contains("name-input")) {
    e.target.closest(".url-card").querySelector(".cancel-name-btn").click();
  }
});

startPolling();
