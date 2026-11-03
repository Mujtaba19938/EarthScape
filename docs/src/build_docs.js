// Turns the Markdown files in this folder into Word files. Run from the repository root, with the docx package available:
// node docs/src/build_docs.js   (then docs/src/finish_docs.ps1 updates the contents pages and writes ReadMe.doc)
const fs = require('fs');
const path = require('path');
const JSZip = require('jszip');
const {
  AlignmentType, BorderStyle, Document, Footer, HeadingLevel, ImageRun, LevelFormat, Packer, PageNumber, PageBreak,
  Paragraph, ShadingType, Table, TableCell, TableOfContents, TableRow, TextRun, WidthType,
} = require('docx');

const ROOT = path.resolve(__dirname, '..', '..');
const GREEN = '14663B';
const FONT = 'Calibri';
const CODE_FONT = 'Consolas';
const PAGE_WIDTH = 9360; // A4 with 1 inch side margins would be 9026; these margins are slightly smaller.
const OUTPUTS = [
  ['user_guide.md', 'docs/EarthScape_User_Guide.docx'],
  ['developer_guide.md', 'docs/EarthScape_Developer_Guide.docx'],
  ['project_report.md', 'docs/EarthScape_Project_Report.docx'],
  ['video_script.md', 'docs/EarthScape_Video_Script.docx'],
  ['readme.md', 'ReadMe.docx'],
];

function inline(text, base = {}) {
  const runs = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) runs.push(new TextRun({ text: text.slice(last, match.index), ...base }));
    const piece = match[0];
    if (piece.startsWith('**')) runs.push(new TextRun({ text: piece.slice(2, -2), bold: true, ...base }));
    else runs.push(new TextRun({ text: piece.slice(1, -1), font: CODE_FONT, size: (base.size || 22) - 2, ...base, font: CODE_FONT }));
    last = match.index + piece.length;
  }
  if (last < text.length) runs.push(new TextRun({ text: text.slice(last), ...base }));
  return runs;
}

function pngSize(file) {
  const data = fs.readFileSync(file);
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20), data };
}

function image(caption, relative) {
  const { width, height, data } = pngSize(path.join(ROOT, relative));
  const shown = Math.min(610, width);
  let scale = shown / width;
  if (height * scale > 760) scale = 760 / height;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true, children: [
      new ImageRun({ type: 'png', data, transformation: { width: Math.round(width * scale), height: Math.round(height * scale) }, altText: { title: caption, description: caption, name: caption } }),
    ] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: caption, italics: true, size: 19, color: '5F6660' })] }),
  ];
}

function table(rows) {
  const count = rows[0].length;
  const longest = rows[0].map((_, i) => Math.max(...rows.map((row) => (row[i] || '').length)));
  const weights = longest.map((n) => Math.max(10, Math.min(n, 60)));
  const total = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map((w) => Math.floor(PAGE_WIDTH * w / total));
  widths[count - 1] += PAGE_WIDTH - widths.reduce((a, b) => a + b, 0);
  const line = { style: BorderStyle.SINGLE, size: 4, color: 'D8DBD8' };
  const borders = { top: line, bottom: line, left: line, right: line };
  return new Table({
    width: { size: PAGE_WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((row, r) => new TableRow({
      tableHeader: r === 0,
      cantSplit: true,
      children: row.map((cell, c) => new TableCell({
        borders,
        width: { size: widths[c], type: WidthType.DXA },
        margins: { top: 50, bottom: 50, left: 90, right: 90 },
        shading: r === 0 ? { type: ShadingType.CLEAR, fill: 'E6F2EB' } : undefined,
        children: [new Paragraph({ children: inline(cell, { size: 19, bold: r === 0 || undefined }) })],
      })),
    })),
  });
}

function parse(markdown) {
  const out = [];
  const lines = markdown.replace(/\r/g, '').split('\n');
  let listId = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (line === '[[pagebreak]]') { out.push(new Paragraph({ children: [new PageBreak()] })); continue; }
    if (line === '[[toc]]') {
      out.push(new Paragraph({ style: 'ContentsTitle', children: [new TextRun('Contents')] }));
      out.push(new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-2' }));
      out.push(new Paragraph({ children: [new PageBreak()] }));
      continue;
    }
    if (line.startsWith('```')) {
      const code = [];
      for (i += 1; !lines[i].startsWith('```'); i += 1) code.push(lines[i]);
      code.forEach((text, n) => out.push(new Paragraph({
        shading: { type: ShadingType.CLEAR, fill: 'F2F3F2' },
        spacing: { before: n === 0 ? 80 : 0, after: n === code.length - 1 ? 160 : 0, line: 250 },
        keepLines: true,
        children: [new TextRun({ text: text || ' ', font: CODE_FONT, size: 18 })],
      })));
      continue;
    }
    const title = line.match(/^= (.+)/);
    if (title) { out.push(new Paragraph({ style: 'Title', children: [new TextRun(title[1])] })); continue; }
    const sub = line.match(/^=- (.+)/);
    if (sub) { out.push(new Paragraph({ style: 'Subtitle', children: [new TextRun(sub[1])] })); continue; }
    const heading = line.match(/^(#{1,3}) (.+)/);
    if (heading) {
      const level = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][heading[1].length - 1];
      out.push(new Paragraph({ heading: level, children: [new TextRun(heading[2])] }));
      continue;
    }
    const picture = line.match(/^!\[(.*)\]\((.+)\)/);
    if (picture) { out.push(...image(picture[1], picture[2])); continue; }
    if (line.startsWith('|')) {
      const rows = [];
      for (; i < lines.length && lines[i].startsWith('|'); i += 1) {
        if (!/^\|[\s:|-]+\|$/.test(lines[i])) rows.push(lines[i].slice(1, -1).split(' | ').map((c) => c.trim().replace(/^\|\s*|\s*\|$/g, '')));
      }
      i -= 1;
      out.push(table(rows));
      out.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
      continue;
    }
    if (line.startsWith('- ')) {
      out.push(new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 60 }, children: inline(line.slice(2)) }));
      continue;
    }
    const numbered = line.match(/^(\d+)\. (.+)/);
    if (numbered) {
      if (numbered[1] === '1') listId += 1;
      out.push(new Paragraph({ numbering: { reference: 'steps', level: 0, instance: listId }, spacing: { after: 60 }, children: inline(numbered[2]) }));
      continue;
    }
    out.push(new Paragraph({ spacing: { after: 120 }, children: inline(line) }));
  }
  return out;
}

async function build(source, target) {
  const doc = new Document({
    creator: 'EarthScape project team',
    title: path.basename(target, path.extname(target)).replace(/_/g, ' '),
    styles: {
      default: { document: { run: { font: FONT, size: 22 }, paragraph: { spacing: { line: 276 } } } },
      paragraphStyles: [
        { id: 'Title', name: 'Title', basedOn: 'Normal', run: { font: FONT, size: 56, bold: true, color: GREEN }, paragraph: { spacing: { before: 0, after: 80 } } },
        { id: 'Subtitle', name: 'Subtitle', basedOn: 'Normal', run: { font: FONT, size: 26, color: '5F6660' }, paragraph: { spacing: { before: 0, after: 280 } } },
        { id: 'ContentsTitle', name: 'Contents Title', basedOn: 'Normal', run: { font: FONT, size: 32, bold: true, color: GREEN }, paragraph: { spacing: { before: 120, after: 120 } } },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 32, bold: true, color: GREEN }, paragraph: { spacing: { before: 320, after: 120 }, keepNext: true, outlineLevel: 0 } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 26, bold: true, color: '040404' }, paragraph: { spacing: { before: 240, after: 80 }, keepNext: true, outlineLevel: 1 } },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 23, bold: true, color: '040404' }, paragraph: { spacing: { before: 180, after: 60 }, keepNext: true, outlineLevel: 2 } },
      ],
    },
    numbering: { config: [
      { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 240 } } } }] },
      { reference: 'steps', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 300 } } } }] },
    ] },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1200, bottom: 1100, left: 1273, right: 1273 } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['EarthScape Climate Agency  |  Page ', PageNumber.CURRENT], size: 17, color: '5F6660' })] })] }) },
      children: parse(fs.readFileSync(path.join(__dirname, source), 'utf8')),
    }],
  });
  // Word asks about this setting in a dialog when it opens the file, which would block finish_docs.ps1.
  const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
  const settings = await zip.file('word/settings.xml').async('string');
  zip.file('word/settings.xml', settings.replace(/<w:updateFields[^>]*\/>/, ''));
  fs.writeFileSync(path.join(ROOT, target), await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  console.log('Wrote', target);
}

(async () => {
  for (const [source, target] of OUTPUTS) await build(source, target);
})().catch((error) => { console.error(error); process.exit(1); });
