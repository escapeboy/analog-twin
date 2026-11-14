// Router: ?film=1 starts the 30 s demo film; ?view=present opens the Presentation view; the analyst UI is the default
// (?view=analyst still works for old links).
// Only one view is built per page load, so they never hold WebGL contexts at the same time.
const q = new URLSearchParams(location.search);
if (q.get('film') === '1') void import('./film/film').then((m) => m.startFilm());
else if (q.get('view') === 'present') void import('./present/app');
else void import('./analyst');
