package userservice

import (
	"context"
	"errors"
	"fmt"
)

type Repository interface {
	FindByID(ctx context.Context, id string) (*User, error)
	Save(ctx context.Context, u *User) error
}

type User struct {
	ID    string
	Name  string
	Email string
}

type Service struct {
	repo Repository
}

func NewService(repo Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) Get(ctx context.Context, id string) (*User, error) {
	if id == "" {
		return nil, errors.New("empty id")
	}
	return s.repo.FindByID(ctx, id)
}

func (s *Service) Create(ctx context.Context, name string) (*User, error) {
	u := &User{Name: name}
	if err := s.repo.Save(ctx, u); err != nil {
		return nil, fmt.Errorf("save: %w", err)
	}
	return u, nil
}

func plainHelper(a, b int) int {
	return a + b
}
