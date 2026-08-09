/** Результат выбора адреса на карте.
 *
 * Экран карты — отдельный маршрут, и вернуть значение через параметры навигации
 * ненадёжно (родительский экран их не перечитывает). Поэтому выбор кладётся сюда,
 * а форма заказа забирает его при возврате фокуса.
 */

export interface PickedAddress {
  latitude: number;
  longitude: number;
  address: string | null;
}

let picked: PickedAddress | null = null;

export function setPickedAddress(value: PickedAddress): void {
  picked = value;
}

/** Забирает выбор и очищает его, чтобы он не подставился в следующий заказ. */
export function takePickedAddress(): PickedAddress | null {
  const value = picked;
  picked = null;
  return value;
}
