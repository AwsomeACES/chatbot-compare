/* Keep bookmarks and shared historical run links working in the unified interface. */
const studioDestination = new URL("/", location.origin);
const savedRun = new URLSearchParams(location.search).get("run");
if (savedRun) studioDestination.searchParams.set("run", savedRun);
studioDestination.hash = "governance";
document.querySelector("a").href = studioDestination.href;
location.replace(studioDestination.href);
