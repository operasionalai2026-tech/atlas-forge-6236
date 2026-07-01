import "./globals.css";

export const metadata = {
  title: "Beverra Central",
  description: "Beverra Central — integrasi Jubelio → Supabase",
};

export default function RootLayout({ children }) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
