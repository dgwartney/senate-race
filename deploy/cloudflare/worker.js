// Fronts the Fly app on a custom domain. Forwards every request, including Streamlit's
// WebSocket upgrade, to the Fly origin.
const ORIGIN = "https://senate-race-tracker.fly.dev";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const headers = new Headers(request.headers);
    // Streamlit rejects WebSocket connections whose Origin doesn't match the host it is served on.
    if (headers.has("Origin")) headers.set("Origin", ORIGIN);
    return fetch(new URL(url.pathname + url.search, ORIGIN), {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });
  },
};
