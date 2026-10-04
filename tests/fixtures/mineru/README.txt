Real `mineru-kit parse <pdf> -o <dir> -f zip --tier standard` output (MinerU 4.0.10, standard tier), cut down.

  looped/   arXiv 2609.36585, first 17 of 32 pages. Multi-panel figures, charts with fake captions ("b", "c"), tables, equations.
  ego2act/  arXiv 2610.01092, first 6 of 51 pages. Charts/images whose captions list starts with panel labels ("(a) ..."),
            then the real "Figure N" caption; a table.

What was changed (copyright: no PDF, no extracted images, no long text is kept):
  - structured_content.json: same blocks, types, bboxes, captions lists and image_source names; every text field cut to
    40 characters; `metadata` and `extensions` reduced to the producer/tier.
  - markdown.md: real line structure, each line cut to 40 characters, cut at the first image of a dropped page.
  - images/: 4x4 gray placeholder jpgs under the real file names (page_{n}_{image|chart|table|equation}_{k}.jpg).
The zip the tool writes also has middle_json.json and model_output.json; they are not kept (PaperBrief does not use them).
