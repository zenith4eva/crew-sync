// One-page filming guide to send crews before they record. Each tip maps to a way tracking or scoring fails.
export const TIPS: [string, string][] = [
  ['Phone on a tripod, facing the crew', 'A moving camera looks like everyone moving. Prop it on something steady if you have no tripod.'],
  ['Landscape, whole crew head to feet', 'Formation is measured from feet. Leave space at the sides for dancers who travel.'],
  ['Film from where the audience would sit', 'Straight on, at chest height. Side angles squash the spacing between rows.'],
  ['Cover or avoid mirrors behind the crew', 'Reflections can be tracked as extra dancers.'],
  ['Nobody walks in front of the camera', 'A person crossing the frame hides dancers and can swap their colors.'],
  ['Play the music out loud', 'The beat comes from the audio. A clear track gives better timing than counts.'],
  ['30 to 90 seconds, one run-through', 'Score the same section each time so before-and-after numbers compare.'],
  ['Good, even light', 'Dark corners and backlight from windows make outlines less accurate.'],
  ['Everyone agrees first', 'Ask every dancer before you film and upload. Videos are deleted after 7 days.'],
];

export default function Guide() {
  return (
    <article className="card guide narrow">
      <h1>How to film your rehearsal</h1>
      <p className="muted">Crew Sync scores every dancer from one video. These steps make the scores accurate.</p>
      <ol>
        {TIPS.map(([tip, why]) => <li key={tip}><b>{tip}</b><br /><span className="muted">{why}</span></li>)}
      </ol>
      <p><a href="#">Upload a video</a></p>
    </article>
  );
}
