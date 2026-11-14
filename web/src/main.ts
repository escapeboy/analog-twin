// Router: ?film=1 starts the 30 s demo film; ?view=analyst opens the full analyst UI; the Presentation view is the default.
// Only one view is built per page load, so they never hold WebGL contexts at the same time.
const q = new URLSearchParams(location.search);
if (q.get('film') === '1') void import('./film/film').then((m) => m.startFilm());
else if (q.get('view') === 'analyst') void import('./analyst');
else void import('./present/app');
