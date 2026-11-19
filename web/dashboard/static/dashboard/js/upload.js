// Shows upload progress. The server checks the file and redirects back with a message.

const form = document.querySelector('form[data-upload]');

if (form && window.XMLHttpRequest && window.FormData) {
  const progress = form.querySelector('[data-upload-progress]');
  const bar = form.querySelector('[data-upload-bar]');
  const label = form.querySelector('[data-upload-label]');
  const button = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const request = new XMLHttpRequest();
    request.open('POST', form.action);
    // JSON reply, not a redirect
    request.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    // Progress bar
    request.upload.onprogress = (step) => {
      if (!step.lengthComputable) return;
      const percent = Math.round(100 * step.loaded / step.total);
      bar.style.width = percent + '%';
      label.textContent = percent < 100 ? 'Uploading ' + percent + '%' : 'Storing in HDFS...';
    };
    // Show the result
    request.onload = () => {
      let next = location.href;
      try { next = JSON.parse(request.responseText).next || next; } catch (error) { next = request.responseURL || next; }
      location.href = next;
    };
    request.onerror = () => { location.reload(); };
    button.classList.add('hidden');
    progress.classList.remove('hidden');
    request.send(new FormData(form));
  });
}
