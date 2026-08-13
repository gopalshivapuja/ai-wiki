/** Node colours by document type.
 *
 * Split out of GraphView so the legend can be rendered without pulling in vis-network — that
 * dependency is ~600KB and should only arrive when someone actually opens a map.
 */
export const TYPE_COLORS: Record<string, string> = {
  zettel: '#6ea8fe',
  concept: '#3dd68c',
  entity: '#f0ad4e',
  literature: '#c77dff',
  moc: '#ff6b6b',
  synthesis: '#adb5bd',
  index: '#ffd166',
  page: '#9b9ba8',
  web: '#7f8c9a',
  pdf: '#7f8c9a',
  youtube: '#7f8c9a',
  audio: '#7f8c9a',
  arxiv: '#7f8c9a',
  note: '#7f8c9a',
};
