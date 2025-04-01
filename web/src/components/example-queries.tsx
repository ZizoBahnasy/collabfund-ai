"use client";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

export function ExampleQueries() {
  return (
    <div className="bg-white p-4 rounded-md border mb-4">
      <h3 className="text-lg font-medium mb-2">Example Queries</h3>
      <Accordion type="single" collapsible className="w-full">
        <AccordionItem value="investment-analysis">
          <AccordionTrigger className="text-sm font-medium">Investment Analysis</AccordionTrigger>
          <AccordionContent>
            <ul className="list-disc pl-5 space-y-2 text-sm">
              <li>"In one sentence, can you tell me about Collaborative Fund's investment style?"</li>
              <li>"In brief terms, can you tell me about how Collaborative Fund's investment style compares to Zizo's?"</li>
              <li>"Which companies align best with Collaborative Fund's investment style?"</li>
              <li>"Can you tell me about three climate companies in our portfolio that we're very excited about?"</li>
              <li>"Can you tell me which three companies in our portfolio have the highest capital intensity and also give me a very brief description of what they do and their defensibility?"</li>
              <li>"Please identify the 5 companies that are least compatible or aligned with the Collaborative Fund investment style but which have an excitement score of 7 or greater."</li>
            </ul>
          </AccordionContent>
        </AccordionItem>
        
        <AccordionItem value="company-deep-dives">
          <AccordionTrigger className="text-sm font-medium">Company Deep Dives</AccordionTrigger>
          <AccordionContent>
            <ul className="list-disc pl-5 space-y-2 text-sm">
              <li>"Tell me about Impossible Foods' defensibility and barriers to entry."</li>
              <li>"What is The Browser Company's most recent valuation?"</li>
              <li>"Which companies have the highest capital intensity?"</li>
            </ul>
          </AccordionContent>
        </AccordionItem>
        
        <AccordionItem value="portfolio-insights">
          <AccordionTrigger className="text-sm font-medium">Portfolio Insights</AccordionTrigger>
          <AccordionContent>
            <ul className="list-disc pl-5 space-y-2 text-sm">
              <li>"Which health companies raised the most money in the last 2 years?"</li>
              <li>"Could you please give me the three most recent news articles about AMP Robotics? Don't read the URLs."</li>
            </ul>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
      
      <div className="mt-4 text-xs text-gray-500 italic">
        <p>Note: It's helpful to guide the speaking style of the agent by saying things like "In very brief, natural speech..." or "In one sentence..." or add "in brief terms" as the agent defaults to returning all available information for whatever field you're asking about.</p>
      </div>
    </div>
  );
}