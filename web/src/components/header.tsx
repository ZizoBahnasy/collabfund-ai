"use client";

import { CodeViewer } from "@/components/code-viewer";
import { PresetSave } from "@/components/preset-save";
import { PresetSelector } from "@/components/preset-selector";
import { PresetShare } from "@/components/preset-share";

export function Header() {
  return (
    <div className="flex flex-shrink-0 flex-col lg:flex-row p-4 border-l border-r border-t border-b rounded-t-md bg-white">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between lg:flex-grow">
        <div className="flex flex-col mb-2 lg:mb-0">
          <div className="flex flex-row items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Collaborative Fund&apos;s Portfolio AI</h2>
              <p className="text-sm text-gray-500">
                Built using LiveKit and OpenAI Realtime API
              </p>
            </div>
          </div>
        </div>
        <div className="flex flex-row items-center justify-between sm:justify-end space-x-2 mt-2 lg:mt-0">
          <div className="flex flex-row items-center space-x-2">
            {/* Removing PresetSelector, PresetSave, PresetShare, and CodeViewer buttons */}
          </div>
        </div>
      </div>
    </div>
  );
}
