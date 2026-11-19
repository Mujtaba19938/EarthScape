// Builds web/dashboard/static/dashboard/tailwind.css, so the dashboard needs no internet. Run from the repository root after changing classes:
// npx tailwindcss@3.4.16 -c deploy/tailwind/tailwind.config.js -i deploy/tailwind/input.css -o web/dashboard/static/dashboard/tailwind.css --minify
const path = require('path');

const web = path.join(__dirname, '..', '..', 'web');

module.exports = {
  content: [
    path.join(web, 'dashboard', 'templates', '**', '*.html'),
    path.join(web, 'accounts', 'templates', '**', '*.html'),
    path.join(web, 'dashboard', 'static', 'dashboard', 'js', '*.js'),
  ],
};
