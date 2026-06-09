// Inventory search page: DataTables init + bulk-select/apply/reprint controls.
// Extracted from the inline <script> in inventory_search.html (Phase 11.2).
document.addEventListener('DOMContentLoaded', function () {
    if (typeof $ === 'undefined') {
        console.error('jQuery not loaded – DataTables will not work.');
        return;
    }

    const table = $('#searchResultsTable').DataTable({
        ordering: true,
        pageLength: 25,
        lengthMenu: [[25, 50, 100, -1], [25, 50, 100, "All"]],
        searching: false,
        // Set per-column flags via columnDefs, never via a per-column
        // header label in the `columns` option. That label option makes
        // DataTables overwrite each header cell's HTML — the empty label
        // on column 0 wiped out the <input id="select-all"> checkbox, and
        // the resulting getElementById('select-all') === null threw before
        // the form submit handler (which injects item_ids) was attached,
        // silently breaking both "Apply" and "Reprint tags". Headers come
        // from the existing <th> text instead.
        columnDefs: [
            {targets: 0, orderable: false, searchable: false},
            {targets: -1, orderable: false}
        ]
    });

    const selectedIds = new Set();

    function getVisibleIds() {
        const ids = [];
        table.rows({page: 'current'}).nodes().each(function (row) {
            const cb = row.querySelector('.row-select');
            if (cb) ids.push(parseInt(cb.dataset.id, 10));
        });
        return ids;
    }

    function syncUI() {
        const count = selectedIds.size;
        const bar = document.getElementById('bulk-action-bar');
        bar.style.display = count > 0 ? 'flex' : 'none';
        document.getElementById('bulk-count-label').textContent =
            count + ' item' + (count !== 1 ? 's' : '') + ' selected';
        document.getElementById('bulk-apply-btn').textContent =
            'Apply to ' + count + ' item' + (count !== 1 ? 's' : '');

        const visibleIds = getVisibleIds();
        const selectAll = document.getElementById('select-all');
        if (visibleIds.length === 0) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        } else {
            const selectedOnPage = visibleIds.filter(id => selectedIds.has(id)).length;
            selectAll.checked = selectedOnPage === visibleIds.length;
            selectAll.indeterminate = selectedOnPage > 0 && selectedOnPage < visibleIds.length;
        }
    }

    // Re-sync checkboxes on every DataTables redraw (page change, sort, initial load)
    table.on('draw.dt', function () {
        table.rows({page: 'current'}).nodes().each(function (row) {
            const cb = row.querySelector('.row-select');
            if (cb) cb.checked = selectedIds.has(parseInt(cb.dataset.id, 10));
        });
        syncUI();
    });

    // Row checkbox toggle
    document.getElementById('searchResultsTable').addEventListener('change', function (e) {
        if (!e.target.classList.contains('row-select')) return;
        const id = parseInt(e.target.dataset.id, 10);
        if (e.target.checked) selectedIds.add(id);
        else selectedIds.delete(id);
        syncUI();
    });

    // Select All toggle (current page only)
    document.getElementById('select-all').addEventListener('change', function () {
        const visibleIds = getVisibleIds();
        if (this.checked) visibleIds.forEach(id => selectedIds.add(id));
        else visibleIds.forEach(id => selectedIds.delete(id));
        table.rows({page: 'current'}).nodes().each(function (row) {
            const cb = row.querySelector('.row-select');
            if (cb) cb.checked = selectedIds.has(parseInt(cb.dataset.id, 10));
        });
        syncUI();
    });

    // Clear button
    document.getElementById('bulk-clear-btn').addEventListener('click', function () {
        selectedIds.clear();
        table.rows().nodes().each(function (row) {
            const cb = row.querySelector('.row-select');
            if (cb) cb.checked = false;
        });
        document.getElementById('select-all').checked = false;
        document.getElementById('select-all').indeterminate = false;
        syncUI();
    });

    // Inject hidden ID inputs on submit
    document.getElementById('bulk-action-form').addEventListener('submit', function () {
        const container = document.getElementById('bulk-id-container');
        container.innerHTML = '';
        selectedIds.forEach(function (id) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'item_ids';
            input.value = id;
            container.appendChild(input);
        });
    });
});
