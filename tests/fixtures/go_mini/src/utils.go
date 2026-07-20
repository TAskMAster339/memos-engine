package main

import "fmt"

var defaultName = "world"

func greet(name string) string {
	return "hello " + name
}

func GreetPublic(name string) string {
	return greet(name)
}
