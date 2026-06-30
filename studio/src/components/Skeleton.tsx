import React from "react";

// Loading placeholder for the thread: reserves layout with a few shimmer rows that
// mimic a couple of exchanges, instead of a single spinner that makes a short wait
// feel longer. The shimmer is killed by the global prefers-reduced-motion rule.
export function ThreadSkeleton() {
  return (
    <div className="threadSkeleton" aria-hidden="true">
      <div className="skelTurn">
        <div className="skel skelUser" />
      </div>
      <div className="skelTurn">
        <div className="skel skelLabel" />
        <div className="skel skelLine" />
        <div className="skel skelLine short" />
      </div>
      <div className="skelTurn">
        <div className="skel skelUser narrow" />
      </div>
      <div className="skelTurn">
        <div className="skel skelLabel" />
        <div className="skel skelLine" />
        <div className="skel skelLine" />
        <div className="skel skelLine short" />
      </div>
    </div>
  );
}
