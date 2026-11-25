// ==========================================================================
// CogniCoach icon set - every icon on the site is an inline SVG from here (no emoji).
//   CogniIcons.svg(name, { size, cls, label })  -> '<svg ...>' string
//   CogniIcons.hydrate(root)                    -> fills <i data-icon="name"></i> placeholders
// Line icons: 24x24, 2px round strokes in currentColor, so they take the text colour.
// Game icons ("coin", "flame", "freeze", "boost", "xp", "chest-*", "medal-*", "trophy-gold",
// "league-*"): full-colour illustrations with their own gradients.
// Decorative by default (aria-hidden); pass { label } to make one an image with a name.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniIcons) { return; }

    // ---------------------------------------------------------------- line icons (path data)
    var L = {
        'volume': '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
        'pause': '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
        'play': '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"/>',
        'stop': '<rect x="6" y="6" width="12" height="12" rx="2"/>',
        'mic': '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
        'sliders': '<path d="M4 6h9"/><path d="M17 6h3"/><circle cx="15" cy="6" r="2"/><path d="M4 12h3"/><path d="M11 12h9"/><circle cx="9" cy="12" r="2"/><path d="M4 18h11"/><path d="M19 18h1"/><circle cx="17" cy="18" r="2"/>',
        'close': '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
        'skip': '<path d="M5 5.5v13a.8.8 0 0 0 1.2.7l9.6-6.5a.8.8 0 0 0 0-1.4L6.2 4.8A.8.8 0 0 0 5 5.5z"/><path d="M19 5v14"/>',
        'check': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
        'check-circle': '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
        'half-circle': '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" stroke="none"/>',
        'lock': '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
        'arrow-up': '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
        'arrow-down': '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
        'arrow-right': '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
        'chevron-right': '<path d="M9 6l6 6-6 6"/>',
        'chevron-down': '<path d="M6 9l6 6 6-6"/>',
        'trend-up': '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
        'trend-down': '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
        'calendar': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 3v4"/><path d="M16 3v4"/>',
        'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        'stopwatch': '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 2"/><path d="M10 2.5h4"/><path d="M12 2.5V6"/><path d="M18.5 6.5l1.5-1.5"/>',
        'target': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/>',
        'message': '<path d="M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z"/>',
        'idea': '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>',
        'accessibility': '<circle cx="12" cy="4.5" r="1.6" fill="currentColor"/><path d="M5 8.5l7 1.5 7-1.5"/><path d="M12 10v5"/><path d="M12 15l-3.5 6"/><path d="M12 15l3.5 6"/>',
        'infinity': '<path d="M7.5 8.5C5.5 8.5 4 10.1 4 12s1.5 3.5 3.5 3.5c3 0 6-7 9-7 2 0 3.5 1.6 3.5 3.5s-1.5 3.5-3.5 3.5c-3 0-6-7-9-7z"/>',
        'bolt': '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
        'leaf': '<path d="M5 20c-.5-9 5.5-15 15-15 .5 9.5-5.5 15-14 15"/><path d="M5 20l8-8"/>',
        'battery-low': '<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/><path d="M5.5 10v4"/>',
        'smile': '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a5 5 0 0 0 7 0"/><path d="M9 9.5h.01"/><path d="M15 9.5h.01"/>',
        'strain': '<circle cx="12" cy="12" r="9"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M8 9l2 1.3"/><path d="M16 9l-2 1.3"/>',
        'thumbs-up': '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-8c1.6 0 2.5 1 2.5 2.5V9h5a2 2 0 0 1 2 2.3l-1.2 7a2 2 0 0 1-2 1.7H7"/>',
        'rocket': '<path d="M5 15c-1.2 1.2-1.5 4.5-1.5 4.5s3.3-.3 4.5-1.5"/><path d="M9 15l-3-3c1-3 3-6.2 6-8 3-1.6 6-1.6 8-1 .6 2 .6 5-1 8-1.8 3-5 5-8 6z"/><circle cx="15" cy="9" r="1.5"/>',
        'hourglass': '<path d="M6 3h12"/><path d="M6 21h12"/><path d="M7 3c0 4 3.5 6 5 9 1.5-3 5-5 5-9"/><path d="M7 21c0-4 3.5-6 5-9 1.5 3 5 5 5 9"/>',
        'flag': '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4L17 12H5"/>',
        'compass': '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
        'globe': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z"/>',
        'runner': '<circle cx="14.5" cy="4.5" r="2"/><path d="M7 21l3-5.5 3 2.5v4"/><path d="M5 11.5 8.5 8h5l2.5 4 3 1"/><path d="M10 15.5 11.5 9"/>',
        'sunrise': '<path d="M3 18h18"/><path d="M7 18a5 5 0 0 1 10 0"/><path d="M12 4v4"/><path d="M5.6 9.6 7 11"/><path d="M18.4 9.6 17 11"/><path d="M8 21.5h8"/>',
        'moon': '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
        'dumbbell': '<path d="M6.5 6.5v11"/><path d="M17.5 6.5v11"/><path d="M3.5 9.5v5"/><path d="M20.5 9.5v5"/><path d="M6.5 12h11"/>',
        'star': '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
        'trophy': '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 4"/><path d="M16 6h3a3 3 0 0 1-3 4"/><path d="M12 13v4"/><path d="M8 21h8"/><path d="M9 17h6v4H9z"/>',
        'medal': '<circle cx="12" cy="15" r="5.5"/><path d="M8.5 3 11 9.7"/><path d="M15.5 3 13 9.7"/><path d="M12 12.5l.9 1.8 2 .3-1.4 1.4.3 2-1.8-.9-1.8.9.3-2-1.4-1.4 2-.3z"/>',
        'flame': '<path d="M12 3c1 3.5 5.5 5.5 5.5 10.5A5.5 5.5 0 0 1 6.5 13.5c0-2.2 1-3.8 2.2-4.8.1 2 1.1 3 2.3 3.2-.4-3.2.2-6 1-8.9z"/>',
        'inbox': '<path d="M3 13l3-8h12l3 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
        'users': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.3c2.2.8 3.5 2.9 3.5 5.7"/>',
        'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
        'user-plus': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M19 7v6"/><path d="M16 10h6"/>',
        'user-check': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 10.5l2 2 4-4"/>',
        'bag': '<path d="M5 8h14l-1.2 11.2a1 1 0 0 1-1 .8H7.2a1 1 0 0 1-1-.8z"/><path d="M9 10V6.5a3 3 0 0 1 6 0V10"/>',
        'gift': '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v8a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-8"/><path d="M12 8v13"/><path d="M12 8C10.5 4 6.5 4.5 7.5 7.2 8 8 12 8 12 8z"/><path d="M12 8c1.5-4 5.5-3.5 4.5-.8C16 8 12 8 12 8z"/>',
        'shield': '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
        'crown': '<path d="M3 7.5l4.5 4.5L12 5l4.5 7L21 7.5 19 19H5z"/><path d="M5 22h14"/>',
        'snowflake': '<path d="M12 2v20"/><path d="M3.3 7l17.4 10"/><path d="M3.3 17 20.7 7"/><path d="M9.5 3.5 12 6l2.5-2.5"/><path d="M9.5 20.5 12 18l2.5 2.5"/><path d="M3.5 10.5l3.3-.9-.9-3.4"/><path d="M20.5 13.5l-3.3.9.9 3.4"/>',
        'home': '<path d="M3 11l9-7 9 7"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
        'grid': '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/>',
        'podium': '<path d="M3 21v-6h6v6"/><path d="M9 21V9h6v12"/><path d="M15 21v-4h6v4"/><path d="M2 21h20"/><path d="M12 3.5l.8 1.6 1.7.2-1.3 1.2.4 1.7L12 7.4l-1.6.8.4-1.7-1.3-1.2 1.7-.2z"/>',
        'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6h.01"/>',
        'mail': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 7l8.5 6 8.5-6"/>',
        'search': '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
        'download': '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>',
        'heart': '<path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.2a4.3 4.3 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z"/>',
        'sparkles': '<path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M19 3v4"/><path d="M17 5h4"/><path d="M18.5 16v3"/><path d="M17 17.5h3"/>',
        'party': '<path d="M3 21l5-14 9 9z"/><path d="M8 7l9 9"/><path d="M14 4c0 1.5 1 2 2 2"/><path d="M18 8c1 0 2 .5 2 2"/><path d="M15.5 2.5h.01"/><path d="M21.5 7.5h.01"/><path d="M20 3l-.5 1.5"/>',
        'rotate-left': '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v5h5"/>',
        'rotate-right': '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M21 4v5h-5"/>',
        'cart': '<path d="M3 4h2l2.2 11a1 1 0 0 0 1 .8h9.4a1 1 0 0 0 1-.8L20 8H6.2"/><circle cx="9" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/>',
        'swords': '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="M13 19l6-6"/><path d="M16 16l4 4"/><path d="M19 21l2-2"/><path d="M9.5 6.5 18 3h3v3l-3.5 8.5"/>',
        'copy': '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
        'refresh': '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16"/><path d="M20 21v-5h-5"/>',
        'logout': '<path d="M9 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
        'eye': '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
        'plus': '<path d="M12 5v14"/><path d="M5 12h14"/>',
        'minus': '<path d="M5 12h14"/>',
        'whistle': '<circle cx="8.5" cy="14.5" r="5"/><path d="M12 11l9-4v4l-6 2.5"/><circle cx="8.5" cy="14.5" r="1.5"/>'
    };

    // ---------------------------------------------------------------- game icons (colour)
    var uid = 0;
    function gid(p) { return 'ci' + p + (++uid); }
    var G = {
        // Grit - the site's currency: an amber hexagon token stamped with a flame
        coin: function () {
            var a = gid('c'), b = gid('c');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffd27a"/><stop offset="0.5" stop-color="#ff9a2e"/><stop offset="1" stop-color="#c2410c"/></linearGradient>' +
                '<linearGradient id="' + b + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff4d6"/><stop offset="1" stop-color="#ffd27a"/></linearGradient></defs>' +
                '<path d="M24 5l17 9.8v19.6L24 44.2 7 34.4V14.8z" fill="#9a3412" transform="translate(0 2)"/>' +
                '<path d="M24 4l17 9.8v19.6L24 43.2 7 33.4V13.8z" fill="url(#' + a + ')" stroke="#9a3412" stroke-width="1.4" stroke-linejoin="round"/>' +
                '<path d="M24 9.5l12.2 7v14L24 37.5 11.8 30.5v-14z" fill="none" stroke="#fff4d6" stroke-width="1.6" stroke-opacity="0.7" stroke-linejoin="round"/>' +
                '<path d="M24.3 14.5c.9 3 5.4 5 5.4 9.8a5.7 5.7 0 0 1-11.4 0c0-2.2 1-3.7 2.2-4.6.1 1.9 1 2.9 2.2 3.1-.3-3 .5-5.6 1.6-8.3z" fill="url(#' + b + ')" stroke="#9a3412" stroke-width="1" stroke-linejoin="round"/>' +
                '<path d="M12 13.5l7-4" stroke="#fff" stroke-width="2.2" stroke-linecap="round" opacity="0.6"/>';
        },
        flame: function () {
            var a = gid('f'), b = gid('f');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ff3d1f"/><stop offset="0.6" stop-color="#ff8a1f"/><stop offset="1" stop-color="#ffc43d"/></linearGradient>' +
                '<linearGradient id="' + b + '" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ffd23d"/><stop offset="1" stop-color="#fff3b0"/></linearGradient></defs>' +
                '<path d="M24 3c2 7 13 11.5 13 24a13 13 0 0 1-26 0c0-5.5 2.6-9.4 5.6-11.8.3 4.6 2.6 7 5.6 7.6C21 16 22 9.6 24 3z" fill="url(#' + a + ')"/>' +
                '<path d="M24.5 22c1.2 4 6.5 5.5 6.5 11a7 7 0 0 1-14 0c0-3 1.4-5 3.3-6.2.3 2.2 1.4 3.4 3 3.6-.6-3-.2-5.7 1.2-8.4z" fill="url(#' + b + ')"/>';
        },
        'flame-off': function () {
            return '<path d="M24 3c2 7 13 11.5 13 24a13 13 0 0 1-26 0c0-5.5 2.6-9.4 5.6-11.8.3 4.6 2.6 7 5.6 7.6C21 16 22 9.6 24 3z" fill="#c9d2de"/>' +
                '<path d="M24.5 22c1.2 4 6.5 5.5 6.5 11a7 7 0 0 1-14 0c0-3 1.4-5 3.3-6.2.3 2.2 1.4 3.4 3 3.6-.6-3-.2-5.7 1.2-8.4z" fill="#e4e9f0"/>';
        },
        freeze: function () {
            var a = gid('z');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#dff4ff"/><stop offset="0.5" stop-color="#6ec8ff"/><stop offset="1" stop-color="#2a78d6"/></linearGradient></defs>' +
                '<path d="M24 3l17 9.5v20L24 42 7 32.5v-20z" fill="url(#' + a + ')" stroke="#1c5cab" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<g stroke="#fff" stroke-width="2.6" stroke-linecap="round" fill="none"><path d="M24 11v25"/><path d="M13.2 17.3l21.6 12.4"/><path d="M13.2 29.7l21.6-12.4"/>' +
                '<path d="M20.5 13 24 16.5 27.5 13"/><path d="M20.5 34 24 30.5l3.5 3.5"/></g>' +
                '<path d="M10 14l8-4.5" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity="0.7"/>';
        },
        boost: function () {
            var a = gid('b');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c9a8ff"/><stop offset="0.5" stop-color="#8a3ffc"/><stop offset="1" stop-color="#4b14a8"/></linearGradient></defs>' +
                '<circle cx="24" cy="25" r="20" fill="#36108a"/><circle cx="24" cy="23" r="20" fill="url(#' + a + ')"/>' +
                '<path d="M26.5 8 13 26h9.5l-2 14L35 21h-9.5z" fill="#ffe680" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>' +
                '<path d="M10 15a15 15 0 0 1 8-7" stroke="#fff" stroke-width="2.4" stroke-linecap="round" fill="none" opacity="0.6"/>';
        },
        xp: function () {
            var a = gid('x');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9fd2ff"/><stop offset="0.55" stop-color="#2a78d6"/><stop offset="1" stop-color="#104281"/></linearGradient></defs>' +
                '<path d="M24 3l18 10.4v21.2L24 45 6 34.6V13.4z" fill="url(#' + a + ')" stroke="#0d366b" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<path d="M26 11 15 26.5h8l-1.5 11L33 21.5h-8z" fill="#fff" stroke="#fff" stroke-width="1" stroke-linejoin="round"/>';
        },
        gem: function () {
            var a = gid('g');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#b3f5ec"/><stop offset="1" stop-color="#1baf7a"/></linearGradient></defs>' +
                '<path d="M14 7h20l9 11-19 24L5 18z" fill="url(#' + a + ')" stroke="#0f7a55" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<path d="M5 18h38M14 7l5 11 5-11 5 11 5-11M19 18l5 24 5-24" fill="none" stroke="#fff" stroke-width="1.2" opacity="0.7"/>';
        },
        'trophy-gold': function () {
            var a = gid('t');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff3b0"/><stop offset="0.5" stop-color="#ffc21f"/><stop offset="1" stop-color="#b8780a"/></linearGradient></defs>' +
                '<path d="M14 5h20v11a10 10 0 0 1-20 0z" fill="url(#' + a + ')" stroke="#9a6400" stroke-width="1.5"/>' +
                '<path d="M14 9H8a7 7 0 0 0 7 9M34 9h6a7 7 0 0 1-7 9" fill="none" stroke="#c98500" stroke-width="3" stroke-linecap="round"/>' +
                '<path d="M21 26h6v7h-6z" fill="#d99a10"/><rect x="14" y="33" width="20" height="9" rx="2" fill="url(#' + a + ')" stroke="#9a6400" stroke-width="1.5"/>' +
                '<path d="M19 9v7" stroke="#fff" stroke-width="2.4" stroke-linecap="round" opacity="0.7"/>';
        }
    };
    function medal(c1, c2, c3) {
        return function () {
            var a = gid('m');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + c1 + '"/><stop offset="0.5" stop-color="' + c2 + '"/><stop offset="1" stop-color="' + c3 + '"/></linearGradient></defs>' +
                '<path d="M15 3h7l4 13h-7zM33 3h-7l-4 13h7z" fill="#2a78d6"/><path d="M22 3h4l-2 7z" fill="#1c5cab"/>' +
                '<circle cx="24" cy="31" r="13" fill="url(#' + a + ')" stroke="' + c3 + '" stroke-width="1.5"/>' +
                '<circle cx="24" cy="31" r="9" fill="none" stroke="#fff" stroke-width="1.4" opacity="0.6"/>' +
                '<path d="M24 25l1.9 3.8 4.2.6-3 3 .7 4.2-3.8-2-3.8 2 .7-4.2-3-3 4.2-.6z" fill="#fff" opacity="0.9"/>';
        };
    }
    G.grit = G.coin;
    G['medal-gold'] = medal('#fff3b0', '#ffc21f', '#b8780a');
    G['medal-silver'] = medal('#ffffff', '#c3cad6', '#7d8796');
    G['medal-bronze'] = medal('#f6cfa8', '#d08a4f', '#7a3f17');

    // Chests: wood / silver / gold. The lid is its own group (class "chest-lid") so it can animate open.
    function chest(body1, body2, band, gem, open) {
        return function () {
            var a = gid('k'), b = gid('k');
            var lid = '<g class="chest-lid"' + (open ? ' transform="rotate(-28 9 21)"' : '') + '>' +
                '<path d="M6 21v-5a10 10 0 0 1 10-10h16a10 10 0 0 1 10 10v5z" fill="url(#' + b + ')" stroke="#3b2208" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<path d="M6 21v-5a10 10 0 0 1 10-10h16a10 10 0 0 1 10 10v5" fill="none" stroke="' + band + '" stroke-width="3"/>' +
                '<rect x="20" y="6" width="8" height="15" fill="' + band + '"/>' +
                '<path d="M11 12a8 8 0 0 1 6-4" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none" opacity="0.45"/></g>';
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + body1 + '"/><stop offset="1" stop-color="' + body2 + '"/></linearGradient>' +
                '<linearGradient id="' + b + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + body1 + '"/><stop offset="1" stop-color="' + body2 + '"/></linearGradient></defs>' +
                (open ? '<ellipse cx="24" cy="21" rx="16" ry="4" fill="#fff3b0" opacity="0.95"/><path d="M14 20l-4-9M24 18V6M34 20l4-9" stroke="#ffe680" stroke-width="2.5" stroke-linecap="round" opacity="0.8"/>' : '') +
                '<rect x="6" y="21" width="36" height="21" rx="3" fill="url(#' + a + ')" stroke="#3b2208" stroke-width="1.5"/>' +
                '<rect x="6" y="21" width="36" height="4" fill="' + band + '"/><rect x="20" y="21" width="8" height="21" fill="' + band + '"/>' +
                '<rect x="21" y="25" width="6" height="8" rx="1.5" fill="' + gem + '" stroke="#3b2208" stroke-width="1"/>' + lid;
        };
    }
    G['chest-wood'] = chest('#c98a4b', '#7a4a1f', '#5b6573', '#ffcc3d', false);
    G['chest-silver'] = chest('#e8edf3', '#8e9aab', '#3f4a5c', '#6ec8ff', false);
    G['chest-gold'] = chest('#ffe680', '#d99a10', '#8a5a00', '#ff3d6e', false);
    G['chest-wood-open'] = chest('#c98a4b', '#7a4a1f', '#5b6573', '#ffcc3d', true);
    G['chest-silver-open'] = chest('#e8edf3', '#8e9aab', '#3f4a5c', '#6ec8ff', true);
    G['chest-gold-open'] = chest('#ffe680', '#d99a10', '#8a5a00', '#ff3d6e', true);

    // League shields (one per league tier), coloured.
    var LEAGUE_COLORS = [['#e7d3c1', '#9c6b43'], ['#e3e9f2', '#7d8796'], ['#fff3b0', '#c98500'], ['#c9fff8', '#1d8c84'],
        ['#d8ecff', '#2f6fe0'], ['#e3cfff', '#6a2ad6'], ['#ffe0a3', '#e0392b']];
    LEAGUE_COLORS.forEach(function (c, i) {
        G['league-' + i] = function () {
            var a = gid('l');
            return '<defs><linearGradient id="' + a + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + c[0] + '"/><stop offset="0.6" stop-color="' + c[1] + '"/><stop offset="1" stop-color="#1b2233"/></linearGradient></defs>' +
                '<path d="M24 3l17 6v12c0 11-7.5 18-17 23C14.5 39 7 32 7 21V9z" fill="url(#' + a + ')" stroke="' + c[0] + '" stroke-width="1.6"/>' +
                '<path d="M24 9l11 4v8.5c0 7.5-5 12.5-11 16-6-3.5-11-8.5-11-16V13z" fill="none" stroke="#fff" stroke-opacity="0.5" stroke-width="1.4"/>' +
                '<text x="24" y="30" text-anchor="middle" font-family="Orbitron, sans-serif" font-weight="900" font-size="13" fill="#fff">' + (i + 1) + '</text>';
        };
    });

    // ---------------------------------------------------------------- API
    function svg(name, opts) {
        opts = opts || {};
        var size = opts.size || 20;
        var label = opts.label ? ' role="img" aria-label="' + String(opts.label).replace(/"/g, '&quot;') + '"' : ' aria-hidden="true" focusable="false"';
        var cls = 'ci ci-' + name + (opts.cls ? ' ' + opts.cls : '');
        if (G[name]) {
            return '<svg class="' + cls + '" width="' + size + '" height="' + size + '" viewBox="0 0 48 48"' + label + '>' + G[name]() + '</svg>';
        }
        var body = L[name] || L.info;
        return '<svg class="' + cls + '" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (opts.stroke || 2) +
            '" stroke-linecap="round" stroke-linejoin="round"' + label + '>' + body + '</svg>';
    }

    function hydrate(root) {
        (root || document).querySelectorAll('i[data-icon]').forEach(function (el) {
            var size = Number(el.getAttribute('data-size')) || undefined;
            var wrap = document.createElement('span');
            wrap.className = 'ci-wrap ' + (el.className || '');
            wrap.innerHTML = svg(el.getAttribute('data-icon'), { size: size, label: el.getAttribute('data-label') || undefined });
            el.replaceWith(wrap);
        });
    }

    window.CogniIcons = { svg: svg, hydrate: hydrate, has: function (n) { return !!(L[n] || G[n]); }, names: function () { return Object.keys(L).concat(Object.keys(G)); } };
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', function () { hydrate(); }); } else { hydrate(); }
})();
