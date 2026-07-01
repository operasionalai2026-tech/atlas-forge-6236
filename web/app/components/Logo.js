// Logo Beverra — huruf "B" bergaya pita dengan gradasi cyan → biru.
// Ganti dengan PNG asli: taruh file di web/public/logo.png lalu pakai <img src="/logo.png" />.
export default function Logo({ size = 44 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Beverra"
      role="img"
    >
      <defs>
        <linearGradient id="bevGrad" x1="18" y1="10" x2="82" y2="92" gradientUnits="userSpaceOnUse">
          <stop stopColor="#5CC8F5" />
          <stop offset="0.5" stopColor="#1E88E5" />
          <stop offset="1" stopColor="#0D47A1" />
        </linearGradient>
      </defs>
      <g
        fill="none"
        stroke="url(#bevGrad)"
        strokeWidth="14"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M35 14 V86" />
        <path d="M35 14 H55 a20 20 0 0 1 0 36 H35" />
        <path d="M35 50 H60 a20 20 0 0 1 0 36 H35" />
      </g>
    </svg>
  );
}
