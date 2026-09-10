/*
 * Shared rendering core for the Viewer pages.
 *
 * Foundation content is markdown carrying MathML, raw LaTeX and figures that
 * live either as [image:img_003] tokens or as the original CDN URL. Turning
 * that into readable HTML is the bulk of a viewer, and is identical whether the
 * page is showing theory, questions or a whole *_final.json -- so it lives here
 * and the pages keep only their own layout and navigation.
 *
 * Loaded as a plain script (the viewers have no build step); everything hangs
 * off window.ContentRender.
 */
(function (global) {
  "use strict";

  // How <math> markup is handled. "typeset" leaves it for MathJax, which
  // renders a real fraction; "plain" flattens it to readable text
  // ("1/v"), which is what the pipeline already does for *_final.json.
  var mathMode = "typeset";
  function setMathMode(mode) { mathMode = (mode === "plain") ? "plain" : "typeset"; }

  var SUPER_MAP = { "0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹","+":"⁺","-":"⁻","n":"ⁿ" };
  function staticAssetUrl(relPath) {
    var p = String(relPath || "").replace(/\\/g, "/").trim();
    if (!p) return "";
    if (/^https?:\/\//i.test(p)) return p;
    if (p[0] !== "/") p = "/" + p;
    return p.split("/").map(function(seg, i) {
      if (!seg) return "";
      return encodeURIComponent(seg);
    }).join("/");
  }
  function imageAssetSrc(asset) {
    if (!asset) return "";
    if (asset.base64) {
      var mime = asset.mime_type || "image/jpeg";
      var b64 = String(asset.base64).replace(/\s+/g, "");
      return "data:" + mime + ";base64," + b64;
    }
    if (asset.file) return staticAssetUrl(asset.file);
    if (asset.source_url && /^https?:\/\//i.test(asset.source_url)) return asset.source_url;
    return "";
  }
  // A figure's cached path only resolves against the server that wrote it, so a
  // copy of a document opened elsewhere records the original URL as a fallback
  // and swaps to it if the local file 404s. Registered as one delegated
  // listener rather than an inline onerror, so no quoting hazards.
  function imageTag(src, alt, asset, rawUrl) {
    var fallback = (asset && asset.source_url) || rawUrl || "";
    var attr = (fallback && fallback !== src && /^https?:\/\//i.test(fallback))
      ? ' data-fallback="' + escAttr(fallback) + '"' : "";
    return '<img class="topic-image" alt="' + esc(alt) + '" loading="lazy" src="' +
      escAttr(src) + '"' + attr + ">";
  }

  document.addEventListener("error", function (event) {
    var el = event.target;
    if (!el || el.tagName !== "IMG") return;
    var fallback = el.getAttribute("data-fallback");
    if (!fallback) return;
    el.removeAttribute("data-fallback");
    el.src = fallback;
  }, true);

  function esc(s) {
    var out = String(s == null ? "" : s);
    out = out.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
    return out;
  }
  function escAttr(s) {
    return esc(s).replaceAll("'", "&#39;");
  }
  function sanitizeSourceText(s) {
    if (s == null) return "";
    return String(s).replace(/<br\s*\/?>/gi, "\n").replace(/\uFFFD/g, "®");
  }
  function needsMathRendering(text) {
    var raw = sanitizeSourceText(text);
    if (!raw.trim()) return false;
    if (/<math[\s>]/i.test(raw)) return true;
    if (/\$\$[\s\S]+?\$\$/.test(raw)) return true;
    if (/(^|[^\\$])\$[^$\n]+?\$/.test(raw)) return true;
    if (/\\\(|\\\[/.test(raw)) return true;
    return false;
  }
  function latexToReadable(latex) {
    var s = String(latex || "").trim();
    s = s.replace(/\\text\{([^{}]*)\}/g, "$1");
    s = s.replace(/\\mathrm\{([^{}]*)\}/g, "$1");
    s = s.replace(/\\mathbf\{([^{}]*)\}/g, "$1");
    s = s.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, "($1)/($2)");
    s = s.replace(/\\frac\{([^{}]+)\}/g, "($1)");
    s = s.replace(/\^\{([^{}]+)\}/g, function(_, exp) {
      if (exp === "circ" || exp.indexOf("°") >= 0) return "°";
      var map = { "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "n": "ⁿ", "+": "⁺", "-": "⁻" };
      var out = "";
      for (var i = 0; i < exp.length; i++) out += map[exp.charAt(i)] || exp.charAt(i);
      return out;
    });
    s = s.replace(/_\{([^{}]+)\}/g, "_$1");
    s = s.replace(/\\circ/g, "°");
    s = s.replace(/\\theta/g, "θ");
    s = s.replace(/\\alpha/g, "α");
    s = s.replace(/\\beta/g, "β");
    s = s.replace(/\\pi/g, "π");
    s = s.replace(/\\mu/g, "μ");
    s = s.replace(/\\times/g, "×");
    s = s.replace(/\\cdot/g, "·");
    s = s.replace(/\\leq/g, "≤");
    s = s.replace(/\\geq/g, "≥");
    s = s.replace(/\\neq/g, "≠");
    s = s.replace(/\\infty/g, "∞");
    s = s.replace(/\\rightarrow/g, "→");
    s = s.replace(/\\leftarrow/g, "←");
    s = s.replace(/\\Rightarrow/g, "⇒");
    s = s.replace(/\\quad/g, " ");
    s = s.replace(/\\left\(/g, "(").replace(/\\right\)/g, ")");
    s = s.replace(/\\[a-zA-Z]+/g, "");
    s = s.replace(/[{}]/g, "");
    return s.replace(/\s+/g, " ").trim();
  }
  function replaceRawLatexInText(text) {
    if (!text || text.indexOf("$") < 0) return text;
    var out = text.replace(/\$\$([\s\S]+?)\$\$/g, function(_, inner) {
      return '<span class="math-plain">' + esc(latexToReadable(inner)) + "</span>";
    });
    out = out.replace(/(^|[^\\$])\$([^$\n]+?)\$(?!\$)/g, function(m, pre, inner) {
      return pre + '<span class="math-plain">' + esc(latexToReadable(inner)) + "</span>";
    });
    return out;
  }
  function replaceRawLatexPlain(text) {
    if (!text || text.indexOf("$") < 0) return text;
    var out = text.replace(/\$\$([\s\S]+?)\$\$/g, function(_, inner) {
      return latexToReadable(inner);
    });
    out = out.replace(/(^|[^\\$])\$([^$\n]+?)\$(?!\$)/g, function(m, pre, inner) {
      return pre + latexToReadable(inner);
    });
    return out;
  }
  function formatSuper(exp) {
    exp = String(exp || "").replace(/\s+/g, "");
    if (!exp) return "";
    if (exp === "circ" || exp.indexOf("°") >= 0) return "°";
    var out = "";
    for (var i = 0; i < exp.length; i++) out += SUPER_MAP[exp.charAt(i)] || exp.charAt(i);
    return out;
  }
  function mathmlLocalTag(node) {
    return String(node.localName || node.nodeName || "").replace(/^.*:/, "").toLowerCase();
  }
  function mathmlJoin(parts) {
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var piece = String(parts[i] || "").replace(/\s+/g, " ").trim();
      if (!piece) continue;
      if (out.length && !/^[,.;:!?)\]}°]/.test(piece) && !/[([{]$/.test(out[out.length - 1])) out.push(" ");
      out.push(piece);
    }
    return out.join("");
  }
  function mathmlNodeToPlain(node) {
    if (!node) return "";
    var tag = mathmlLocalTag(node);
    if (tag === "math" || tag === "mrow" || tag === "mstyle" || tag === "semantics") {
      var kids = [];
      for (var c = node.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 1) kids.push(mathmlNodeToPlain(c));
      }
      return mathmlJoin(kids);
    }
    if (tag === "mn" || tag === "mi" || tag === "mtext" || tag === "ms" || tag === "mo") {
      return (node.textContent || "").replace(/\s+/g, " ").trim();
    }
    if (tag === "mspace") return " ";
    if (tag === "mfrac") {
      var ch = node.children;
      if (ch.length >= 2) {
        var num = mathmlNodeToPlain(ch[0]), den = mathmlNodeToPlain(ch[1]);
        if (/^[\w\d.]+$/.test(num) && /^[\w\d.]+$/.test(den)) return num + "/" + den;
        return "(" + num + ")/(" + den + ")";
      }
      return ch.length ? mathmlNodeToPlain(ch[0]) : "";
    }
    if (tag === "msup") {
      var ch2 = node.children;
      if (ch2.length >= 2) return mathmlNodeToPlain(ch2[0]) + formatSuper(mathmlNodeToPlain(ch2[1]));
      return ch2.length ? mathmlNodeToPlain(ch2[0]) : "";
    }
    if (tag === "msub" || tag === "msubsup" || tag === "msqrt" || tag === "mroot" || tag === "mfenced") {
      var bits = [];
      for (var j = 0; j < node.children.length; j++) bits.push(mathmlNodeToPlain(node.children[j]));
      return mathmlJoin(bits);
    }
    return (node.textContent || "").replace(/\s+/g, " ").trim();
  }
  function mathmlBlockToReadable(block) {
    try {
      var safe = block.replace(/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/g, "&amp;");
      var doc = new DOMParser().parseFromString(safe, "application/xml");
      var root = doc.documentElement;
      if (!root || root.nodeName === "parsererror") {
        doc = new DOMParser().parseFromString(safe, "text/html");
        root = doc.querySelector("math") || doc.body.firstElementChild;
      }
      if (!root) return block;
      var plain = mathmlNodeToPlain(root).trim();
      return plain;
    } catch (e) {
      return block;
    }
  }
  function replaceMathMLInText(text) {
    if (!text || !/<math[\s>]/i.test(text)) return text;
    return text.replace(/<math[\s\S]*?<\/math>/gi, function(block) {
      var plain = mathmlBlockToReadable(block);
      return '<span class="math-plain">' + esc(plain) + "</span>";
    });
  }
  function buildImageMap(source) {
    var map = {};
    // Accepts a topic (with .image_assets) or a bare assets object/array.
    var assets = (source && source.image_assets) || source || {};
    if (Array.isArray(assets)) {
      for (var i = 0; i < assets.length; i++) {
        var a = assets[i];
        if (a && a.id) map[a.id] = a;
      }
    } else {
      Object.keys(assets).forEach(function(id) {
        var a = assets[id] || {};
        map[id] = {
          id: id,
          file: a.file || "",
          base64: a.base64 || "",
          mime_type: a.mime_type || "image/jpeg",
          source_url: a.source_url || "",
        };
      });
    }
    return map;
  }
  function buildImageUrlMap(imageMap) {
    var byUrl = {};
    Object.keys(imageMap || {}).forEach(function(id) {
      var url = (imageMap[id] || {}).source_url;
      if (url) byUrl[String(url).trim()] = imageMap[id];
    });
    return byUrl;
  }
  function injectImages(text, imageMap, imageByUrl) {
    var raw = String(text == null ? "" : text);
    if (!raw.trim()) return raw;
    imageMap = imageMap || {};
    raw = raw.replace(/\[image:\s*(img_\d+)\]/gi, function(_match, id) {
      var src = imageAssetSrc(imageMap[id]);
      if (!src) {
        return '<span class="chip warn">[missing image: ' + esc(id) + "]</span>";
      }
      return imageTag(src, id, imageMap[id]);
    });
    raw = raw.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function(_match, alt, url) {
      // Prefer the cached copy over the CDN when the asset map knows this
      // URL: exercise questions are re-parsed from source markdown after the
      // tokenising pass, so they still carry the original remote URL.
      var cached = (imageByUrl || {})[String(url).trim()];
      var src = (cached && imageAssetSrc(cached)) || staticAssetUrl(url) || url;
      return '<img class="topic-image" alt="' + esc(alt || "image") + '" loading="lazy" src="' + escAttr(src) + '">';
    });
    return raw;
  }
  // "## Heading" on its own line -> a real heading. Used by the markup-preserving
  // branch of renderRichContent; the plain-text branch builds headings itself so
  // it can escape their text.
  function promoteHeadings(raw) {
    return String(raw).replace(/^[ \t]*(#{1,6})[ \t]+(.+?)[ \t]*$/gm, function(_m, hashes, title) {
      var level = Math.min(hashes.length + 2, 6);
      return "<h" + level + ">" + esc(title) + "</h" + level + ">";
    });
  }

  function renderRichContent(text, imageMap, imageByUrl) {
    var raw = sanitizeSourceText(text);
    if (!raw.trim()) return "";
    raw = injectImages(raw, imageMap, imageByUrl);
    if (mathMode === "plain" && /<math[\s>]/i.test(raw)) raw = replaceMathMLInText(raw);
    var hasRawLatex = /(^|[^\\$])\$[^$\n]+?\$/.test(raw) || /\$\$[\s\S]+?\$\$/.test(raw);
    if (hasRawLatex) raw = replaceRawLatexInText(raw);
    if (/<math[\s>]/i.test(raw) || /<img[\s>]/i.test(raw) || /<table[\s>]/i.test(raw) ||
        /<span class="math-plain"/i.test(raw) || needsMathRendering(raw)) {
      // This branch keeps the text as-is to preserve the markup already in it,
      // so markdown headings have to be promoted here too -- otherwise a
      // section that happens to contain a figure shows a literal "## Heading".
      return '<div class="rich math-body">' + promoteHeadings(raw) + "</div>";
    }
    var lines = raw.replace(/\r/g, "").split("\n");
    var parts = [], paragraph = [], inList = false;
    function flushP() {
      if (!paragraph.length) return;
      parts.push("<p>" + esc(replaceRawLatexPlain(paragraph.join(" "))) + "</p>");
      paragraph = [];
    }
    function flushList() {
      if (inList) { parts.push("</ul>"); inList = false; }
    }
    for (var i = 0; i < lines.length; i++) {
      var t = lines[i].trim();
      if (!t) { flushP(); flushList(); continue; }
      var bullet = /^[-*•]\s+(.*)$/.exec(t) || /^\(\w+\)\s+(.*)$/.exec(t);
      if (bullet) {
        flushP();
        if (!inList) { parts.push("<ul>"); inList = true; }
        parts.push("<li>" + esc(replaceRawLatexPlain(bullet[1] || bullet[0])) + "</li>");
        continue;
      }
      var heading = /^(#{1,6})\s+(.*)$/.exec(t);
      if (heading) {
        flushP(); flushList();
        var lvl = Math.min(heading[1].length + 2, 6);
        parts.push("<h" + lvl + ">" + esc(heading[2]) + "</h" + lvl + ">");
        continue;
      }
      paragraph.push(t);
    }
    flushP(); flushList();
    return '<div class="rich">' + parts.join("") + "</div>";
  }
  function renderInlineContent(text, imageMap, imageByUrl) {
    var raw = sanitizeSourceText(text);
    if (!raw.trim()) return "";
    raw = injectImages(raw, imageMap, imageByUrl);
    if (mathMode === "plain" && /<math[\s>]/i.test(raw)) raw = replaceMathMLInText(raw);
    if (/(^|[^\\$])\$[^$\n]+?\$/.test(raw) || /\$\$[\s\S]+?\$\$/.test(raw)) {
      raw = replaceRawLatexInText(raw);
    }
    return '<span class="rich" style="display:inline">' + raw + "</span>";
  }
  function stripInlineOptions(text, options) {
    if (!options || Array.isArray(options.column_1)) return text;
    if (!Object.keys(options).length) return text;
    var lines = String(text == null ? "" : text).split("\n");
    var cut = -1;
    for (var i = 0; i < lines.length; i++) {
      if (/^\s*\(?[a-eA-E][).]\s/.test(lines[i])) { cut = i; break; }
    }
    if (cut <= 0) return text;
    return lines.slice(0, cut).join("\n").replace(/\s+$/, "");
  }
  // Matching questions carry two labelled lists. Shown side by side so a
  // reviewer can check the pairing at a glance; the panes stack on a narrow
  // screen and a Column II entry is often a figure rather than text.
  function renderMatchingLists(list1, list2, imageMap, imageByUrl) {
    function pane(title, items) {
      if (!items || !items.length) return "";
      var rows = items.map(function (item) {
        // A List II entry is often a figure; cap it so one graph does not push
        // the rest of the pairing off the screen.
        return '<li style="margin:4px 0;display:flex;gap:8px;align-items:flex-start">' +
          '<span class="chip" style="flex:none">' + esc(item.id) + "</span>" +
          '<span style="flex:1;min-width:0">' +
          renderInlineContent(item.text, imageMap, imageByUrl) + "</span></li>";
      }).join("");
      return '<div class="match-pane" style="flex:1;min-width:200px"><div class="label">' + esc(title) + "</div>" +
        '<ul style="list-style:none;padding-left:0;margin:0">' + rows + "</ul></div>";
    }
    var panes = pane("List I", list1) + pane("List II", list2);
    if (!panes) return "";
    return '<div class="row" style="margin-top:10px;align-items:flex-start;gap:18px">' +
      panes + "</div>";
  }

  // An MCQ answer is often just the letter ("b"), which only means something
  // next to the options. Render the choices and mark the key.
  function renderOptions(options, answer, imageMap, imageByUrl) {
    if (!options) return "";
    var key = String(answer == null ? "" : answer).trim().toLowerCase().replace(/^\(|\)$/g, "");

    // Matching questions supply options as [{id, text}]; every other type
    // supplies {a: "...", b: "..."}. Normalise to one shape.
    var entries;
    if (Array.isArray(options)) {
      entries = options.map(function (o) { return [String(o.id), o.text]; });
    } else if (Array.isArray(options.column_1) || Array.isArray(options.column_2)) {
      return renderMatchingLists(
        (options.column_1 || []).map(function (t, i) { return { id: String(i + 1), text: t }; }),
        (options.column_2 || []).map(function (t, i) { return { id: String(i + 1), text: t }; }),
        imageMap, imageByUrl);
    } else {
      entries = Object.keys(options).map(function (k) { return [k, options[k]]; });
    }
    if (!entries.length) return "";

    var rows = entries.map(function (entry) {
      var correct = entry[0].toLowerCase() === key;
      return '<li style="margin:2px 0' + (correct ? ";font-weight:600" : "") + '">' +
        '<span class="chip' + (correct ? " good" : "") + '">' + esc(entry[0]) + "</span> " +
        renderInlineContent(entry[1], imageMap, imageByUrl) +
        (correct ? ' <span class="chip good">correct</span>' : "") +
        "</li>";
    });
    return '<div style="margin-top:10px"><div class="label">Options</div><ul style="list-style:none;padding-left:0">' +
      rows.join("") + "</ul></div>";
  }

  function typesetMath(target) {
    if (!window.MathJax) return Promise.resolve();
    var scope = [target || document.body];
    if (MathJax.startup && MathJax.startup.promise) {
      return MathJax.startup.promise.then(function() {
        return MathJax.typesetPromise(scope);
      });
    }
    if (MathJax.typesetPromise) return MathJax.typesetPromise(scope);
    return Promise.resolve();
  }

  // Readable text out of rendered markup, for searching and filtering: a stem
  // carrying MathML is mostly tags, so a raw substring match would hit
  // attribute names instead of the words on screen.
  function plainText(html) {
    var s = String(html == null ? "" : html);
    if (s.indexOf("<") >= 0) {
      s = s.replace(/<math[\s\S]*?<\/math>/gi, " ").replace(/<[^>]+>/g, " ");
    }
    return s.replace(/&[a-z]+;|&#x?[0-9a-f]+;/gi, " ").replace(/\s+/g, " ").trim();
  }

  global.ContentRender = {
    setMathMode: setMathMode,
    esc: esc,
    escAttr: escAttr,
    sanitizeSourceText: sanitizeSourceText,
    staticAssetUrl: staticAssetUrl,
    imageAssetSrc: imageAssetSrc,
    buildImageMap: buildImageMap,
    buildImageUrlMap: buildImageUrlMap,
    injectImages: injectImages,
    renderRichContent: renderRichContent,
    renderInlineContent: renderInlineContent,
    renderOptions: renderOptions,
    renderMatchingLists: renderMatchingLists,
    stripInlineOptions: stripInlineOptions,
    typesetMath: typesetMath,
    plainText: plainText,
  };
})(window);
