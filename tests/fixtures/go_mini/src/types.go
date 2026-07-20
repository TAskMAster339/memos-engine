package main

type User struct {
	Name string
	Age  int
}

type Printer interface {
	Print() error
}

type UserList []User
