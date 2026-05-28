import type { Metadata } from "next";
import Link from "next/link";
import { getConfig } from "@/lib/app-config";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "kArena.io",
    template: "%s - kArena.io",
  },
  description: "Live-kBench evaluation dashboard for kArena research data.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { githubUrl, paperUrl } = getConfig();

  return (
    <html lang="en">
      <body>
        <nav className="topNav" aria-label="Primary navigation">
          <Link className="brand" href="/">
            kArena.io
          </Link>
          <div className="navLinks">
            <Link href="/leaderboard">Leaderboard</Link>
            <Link href="/datasets">Datasets</Link>
            <Link href="/research">Research</Link>
            {paperUrl ? (
              <a className="externalNavLink" href={paperUrl} rel="noreferrer" target="_blank">
                Paper
                <svg aria-hidden="true" fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
                  <path d="M15 3h6v6" />
                  <path d="M10 14 21 3" />
                  <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
                </svg>
              </a>
            ) : null}
            {githubUrl ? (
              <a className="externalNavLink" href={githubUrl} rel="noreferrer" target="_blank">
                GitHub
                <svg aria-hidden="true" fill="currentColor" height="14" viewBox="0 0 24 24" width="14">
                  <path d="M12 .5a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.04c-3.34.73-4.04-1.42-4.04-1.42-.55-1.39-1.34-1.76-1.34-1.76-1.09-.75.08-.73.08-.73 1.21.09 1.85 1.24 1.85 1.24 1.07 1.84 2.81 1.31 3.5 1 .11-.78.42-1.31.76-1.61-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.49 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.83.58A12 12 0 0 0 12 .5Z" />
                </svg>
              </a>
            ) : null}
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
