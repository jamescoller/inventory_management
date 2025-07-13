# Inventory Management Project Recommendations

---

## Setting status based on location

* When a product's location is changed, the status should be updated accordingly.
  * Receiving -> New
  * Dryers -> Drying
  * Dry Storage -> Stored
  * [Printer] -> In-Use
---

## Improve Depleated status action

* Create a binary for depleated and for sold
* Binary single button on the inventory edit view to move item

## Inventory Analytics Dashboard

- **Real-Time Dashboard**
  - Product counts by type/location.
  - Usage trends and top-used items.

- **Visualization Tools**
  - Chart.js or Plotly.

---

## Documentation with Sphinx & GitHub Pages

- **Sphinx Setup**
  ```bash
  pip install sphinx sphinx-autodoc-typehints sphinx-rtd-theme
  sphinx-quickstart docs
  ```

- **GitHub Actions for Docs Deployment**
  ```yaml
  jobs:
    build-docs:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v4
          with:
            python-version: '3.11'
        - run: pip install -r requirements.txt
        - run: cd docs && make html
        - uses: peaceiris/actions-gh-pages@v4
          with:
            github_token: ${{ secrets.GITHUB_TOKEN }}
            publish_dir: ./docs/_build/html
  ```

---

## Best Practices & Learning

- **Django Development**
  - Class-based views, modular apps, optimized queries.

- **Security & Performance**
  - Robust input validation, caching strategies.

- **Continuous Learning**
  - Maintain documentation, code reviews, experiments.

---
