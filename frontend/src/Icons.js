// Line icons, all in the same hand: 1.4px strokes,
// round caps, `currentColor`, so dark mode and hover states follow the text.
// They replace the emoji glyphs the UI used before -- an emoji brings its own
// palette, and this design has exactly one colour.
import React from 'react';

function Svg({ size = 18, children, className }) {
  return (
    <svg className={className ? `icon ${className}` : 'icon'} width={size} height={size}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const IconSearch = (p) => (
  <Svg {...p}><circle cx="10.5" cy="10.5" r="6" /><line x1="15" y1="15" x2="20" y2="20" /></Svg>
);

export const IconLink = (p) => (
  <Svg {...p}>
    <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2" />
    <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2" />
  </Svg>
);

export const IconSun = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
  </Svg>
);

export const IconMoon = (p) => (
  <Svg {...p}><path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z" /></Svg>
);

// "Follow the system": a half-filled circle, the only filled shape in the set.
export const IconAuto = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="7.5" />
    <path d="M12 4.5a7.5 7.5 0 0 1 0 15z" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconChevronLeft = (p) => (
  <Svg {...p}><polyline points="14.5 5 8 12 14.5 19" /></Svg>
);

export const IconChevronRight = (p) => (
  <Svg {...p}><polyline points="9.5 5 16 12 9.5 19" /></Svg>
);

export const IconChevronDown = (p) => (
  <Svg {...p}><polyline points="6 9.5 12 15.5 18 9.5" /></Svg>
);

export const IconCalendar = (p) => (
  <Svg {...p}>
    <rect x="4" y="5.5" width="16" height="14" />
    <line x1="4" y1="10" x2="20" y2="10" />
    <line x1="8.5" y1="3.5" x2="8.5" y2="7" /><line x1="15.5" y1="3.5" x2="15.5" y2="7" />
  </Svg>
);

export const IconPlate = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="6.5" /><circle cx="12" cy="12" r="3.5" />
    <line x1="2.5" y1="5" x2="2.5" y2="19" /><line x1="21.5" y1="5" x2="21.5" y2="19" />
  </Svg>
);

export const IconAlert = (p) => (
  <Svg {...p}>
    <path d="M12 4l9 16H3z" /><line x1="12" y1="10" x2="12" y2="14" />
    <line x1="12" y1="17" x2="12" y2="17.2" />
  </Svg>
);

export const IconPencil = (p) => (
  <Svg {...p}><path d="M5 19l1-4L16 5l3 3L9 18z" /><line x1="14" y1="7" x2="17" y2="10" /></Svg>
);

export const IconComment = (p) => (
  <Svg {...p}><path d="M4 5h16v11H10l-4 3.5V16H4z" /></Svg>
);

export const IconStreak = (p) => (
  <Svg {...p}>
    <path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.5 1.5-4 2.5-5 .3 2 1.2 3 2 3.2C12.3 9 11 6 12 3z" />
  </Svg>
);
