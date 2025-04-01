"use client";

import Logo from "@/assets/lk.svg";
import Image from 'next/image';
import collabfundLogo from '@/assets/collabfund_ai.png';

export default function LK() {
  return (
    <a
      href="https://collabfund.com"
      className="hover:opacity-70 transition-all duration-250"
      target="_blank"
      rel="noopener noreferrer"
    >
      <Image 
        src={collabfundLogo}
        alt="Collaborative Fund AI"
        width={76}
        height={76}
        style={{ objectFit: 'contain' }}
      />
    </a>
  );
}
