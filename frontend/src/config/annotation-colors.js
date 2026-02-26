export const colorMap = {
  yellow: 'bg-amber-400',
  green: 'bg-emerald-400',
  blue: 'bg-blue-400',
  pink: 'bg-pink-400',
  purple: 'bg-violet-400',
}

export const colorOptions = ['yellow', 'green', 'blue', 'pink', 'purple']

export function annotationColor(color) {
  return colorMap[color] || 'bg-amber-400'
}
