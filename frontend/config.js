// API base address for every page. Loaded BEFORE js/api.js.
// To move the API (for example to AWS), change the production URL below
// and add the new origin to CORS_EXTRA_ORIGINS on the server and to
// connect-src in vercel.json.
(function () {
  var host = window.location.hostname;
  var isLocal = host === "localhost" || host === "127.0.0.1";
  if (!window.MEDSCRIBE_API_BASE) {
    window.MEDSCRIBE_API_BASE = isLocal
      ? "http://localhost:8000"
      : "https://medical-ai-mvv1.onrender.com";
  }
})();