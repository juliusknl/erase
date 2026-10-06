// Local, non-paginated tables. The paginated broker library sorts on the server.
document.querySelectorAll('table[data-sortable]').forEach(table => {
  const body = table.tBodies[0];
  if (!body || !body.rows.length || body.rows[0].cells[0].colSpan > 1) return;
  const headers = Array.from(table.querySelectorAll('thead th[data-sort]'));
  const originalOrder = new Map(Array.from(body.rows, (row, index) => [row, index]));
  const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
  function updateHeader(header, direction) {
    header.setAttribute('aria-sort', direction || 'none');
    header.querySelector('[aria-hidden]').textContent = direction === 'ascending' ? '↑' : direction === 'descending' ? '↓' : '↕';
    header.querySelector('button').setAttribute('aria-label', `Sort by ${header.dataset.label}, ${direction === 'ascending' ? 'descending' : 'ascending'}`);
  }
  headers.forEach(header => {
    header.scope = 'col';
    header.dataset.label = header.textContent.trim();
    const button = document.createElement('button');
    button.type = 'button'; // Never submit the batch-send form when sorting.
    button.className = 'table-sort';
    button.append(document.createTextNode(header.dataset.label + ' '));
    const arrow = document.createElement('span');
    arrow.setAttribute('aria-hidden', 'true');
    button.append(arrow);
    header.replaceChildren(button);
    updateHeader(header, header.getAttribute('aria-sort'));
    button.addEventListener('click', () => {
      const direction = header.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
      const factor = direction === 'ascending' ? 1 : -1;
      const value = row => {
        const cell = row.cells[header.cellIndex];
        return cell.dataset.sortValue ?? cell.textContent.trim();
      };
      const rows = Array.from(body.rows).sort((a, b) => {
        const av = value(a), bv = value(b);
        // Keep missing dates last in either direction.
        if (!av || !bv) return av ? -1 : bv ? 1 : originalOrder.get(a) - originalOrder.get(b);
        const comparison = header.dataset.sort === 'number' ? Number(av) - Number(bv) : collator.compare(av, bv);
        return comparison * factor || originalOrder.get(a) - originalOrder.get(b);
      });
      rows.forEach(row => body.append(row)); // Preserve checked boxes and links.
      headers.forEach(other => updateHeader(other, other === header ? direction : null));
    });
  });
});
