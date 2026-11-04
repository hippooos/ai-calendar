export function resolveQuestionAnswer({ selectedValue, customValue, freeTextValue }) {
  const selected = selectedValue?.trim() ?? '';
  const custom = customValue?.trim() ?? '';
  const freeText = freeTextValue?.trim() ?? '';
  if (selected && selected !== '__custom__') return selected;
  if (selected === '__custom__') return custom;
  return custom || freeText;
}
