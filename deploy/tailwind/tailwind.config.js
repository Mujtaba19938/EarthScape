// Builds frontend/css/dashboard.css, so the dashboard needs no internet. Run from the repository root after changing classes:
// npx tailwindcss@3.4.16 -c deploy/tailwind/tailwind.config.js -i deploy/tailwind/input.css -o frontend/css/dashboard.css --minify
const path = require('path');

const frontend = path.join(__dirname, '..', '..', 'frontend');

module.exports = {
  content: [path.join(frontend, 'dashboard.html'), path.join(frontend, 'js', 'earthscape.js')],
};
