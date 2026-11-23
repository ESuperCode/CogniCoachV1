// A small port of Python's difflib.SequenceMatcher.ratio and get_close_matches (no junk heuristics:
// motion names are far shorter than the 200 characters where difflib's autojunk starts).

function matchingBlocksCount(a, b) {
  const b2j = new Map();
  for (let j = 0; j < b.length; j++) {
    if (!b2j.has(b[j])) b2j.set(b[j], []);
    b2j.get(b[j]).push(j);
  }
  const findLongest = (alo, ahi, blo, bhi) => {
    let besti = alo, bestj = blo, bestsize = 0;
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) {
          besti = i - k + 1; bestj = j - k + 1; bestsize = k;
        }
      }
      j2len = newj2len;
    }
    return [besti, bestj, bestsize];
  };
  let matches = 0;
  const queue = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = findLongest(alo, ahi, blo, bhi);
    if (k) {
      matches += k;
      if (alo < i && blo < j) queue.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
    }
  }
  return matches;
}

export function ratio(a, b) {
  const len = a.length + b.length;
  return len ? (2 * matchingBlocksCount(a, b)) / len : 1;
}

function quickRatio(a, b) {
  const avail = new Map();
  for (const ch of b) avail.set(ch, (avail.get(ch) || 0) + 1);
  let matches = 0;
  for (const ch of a) {
    const n = avail.get(ch) || 0;
    if (n > 0) { matches++; avail.set(ch, n - 1); }
  }
  const len = a.length + b.length;
  return len ? (2 * matches) / len : 1;
}

export function getCloseMatches(word, possibilities, n = 3, cutoff = 0.6) {
  const result = [];
  for (const x of possibilities) {
    // difflib: s.set_seq2(word), s.set_seq1(x) -> ratio of (x, word)
    const len = x.length + word.length;
    const rq = len ? (2 * Math.min(x.length, word.length)) / len : 1;
    if (rq >= cutoff && quickRatio(x, word) >= cutoff) {
      const r = ratio(x, word);
      if (r >= cutoff) result.push([r, x]);
    }
  }
  result.sort((p, q) => (q[0] - p[0]) || (q[1] > p[1] ? 1 : q[1] < p[1] ? -1 : 0));
  return result.slice(0, n).map((r) => r[1]);
}
