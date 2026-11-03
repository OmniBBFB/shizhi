# Embedded font fixture

`embedded-serif.pdf` is generated from `embedded-serif.ps` using Ghostscript:

```sh
gs -q -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -dEmbedAllFonts=true \
  -dSubsetFonts=true -sOutputFile=web/tests/fixtures/embedded-serif.pdf \
  web/tests/fixtures/embedded-serif.ps
```

It contains an embedded Type 1C serif font. PDF.js converts this font to
OpenType, exercising the font-table code that uses `Math.sumPrecise`.
The font is Ghostscript's Nimbus Roman (URW Base 35); see
`URW-FONT-LICENSE.txt` for its AGPL license and font embedding exception.
The fixture contains only the sentence “Embedded serif font”.
