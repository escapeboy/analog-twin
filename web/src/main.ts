// Router: the Presentation view is the default; ?view=analyst opens the full analyst UI. Only one view is built per page
// load, so the two never hold WebGL contexts at the same time.
const view = new URLSearchParams(location.search).get('view');
if (view === 'analyst') void import('./analyst');
else void import('./present/app');
