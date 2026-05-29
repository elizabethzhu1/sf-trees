# sf-trees

Visualizing all the trees in San Francisco.

Data sourced from DataSF's Open Data Portal!

Run locally:

```sh
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/index.html`.

The map loads `neighborhoods-map.geojson` and `neighborhood-summary.json`
first, then fetches one `tree-data/<neighborhood>.json` file only after a
neighborhood is selected. If `Street_Tree_List_20260521.csv` or
`neighborhoods.geojson` changes, regenerate the optimized files:

```sh
python3 build-data.py
```
