import { User } from "./types";

export function greet(user: User): string {
  return `Hello, ${user.name}!`;
}

function helper(): void {
  // internal helper
}
