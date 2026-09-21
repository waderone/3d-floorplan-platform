# Third-party notices

The root [MIT license](LICENSE) covers code and documentation authored for this
repository. It does not replace the licenses of third-party dependencies,
submodules, models, textures, HDR images, or datasets.

## Pascal Editor

`spikes/pascal-editor/upstream` pins the public
[Pascal Editor](https://github.com/pascalorg/editor) repository at commit
`a59074774898116c0e7116b424b371e5e3420ea4`. Pascal Editor is distributed under
the MIT License and retains its own copyright and license file inside the
submodule.

## 3D and rendering assets

- Poly Haven assets are available under CC0-1.0. Exact source URLs, authors,
  integrity hashes, and local notices are recorded in
  `packages/asset-catalog/catalog.json`, `packages/render-assets/catalog.json`,
  and `packages/cinematic-assets/catalog.json`.
- Kenney starter assets are available under CC0-1.0. See
  `packages/asset-catalog/LICENSE-KENNEY.txt`.
- Project-authored models explicitly identified in the asset catalog are
  dedicated under CC0-1.0. See the adjacent `LICENSE-PROJECT-ASSETS.txt` and
  `LICENSE-BEDROOM-BENCHMARK.txt` notices.

## Recognition data

Redistributable dataset metadata records the source, rights evidence, license,
and storage policy for each sample. Images marked `local-only` are deliberately
excluded from Git and are not covered by the root license. Contributors must
not commit source images unless redistribution is explicitly allowed.

## Package dependencies

JavaScript and Python dependencies retain their own licenses. Lockfiles and
requirements files are the authoritative dependency inventory. Contributors
must review license compatibility before introducing or redistributing a new
dependency or asset.
