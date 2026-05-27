require 'json'
require_relative 'logger'

module Users
  class BaseService
    def name; 'base'; end
  end

  class UserService < BaseService
    def initialize(repo)
      @repo = repo
    end

    def find(id)
      @repo.find(id)
    end

    def create(attrs)
      validate(attrs)
      @repo.save(attrs)
    end

    private

    def validate(attrs)
      raise 'invalid' if attrs.nil?
    end
  end

  def self.helper(a, b)
    a + b
  end
end
