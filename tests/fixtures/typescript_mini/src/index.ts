import { greet } from "./utils";
import type { User } from "./types";

export function main(): void {
  const user: User = { name: "Alice", age: 30 };
  greet(user);
}
