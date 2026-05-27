library(dplyr)
library(ggplot2)
require(magrittr)
source("utils.R")

add <- function(a, b) {
  a + b
}

greet <- function(name) {
  message <- paste("hello", name)
  print(message)
}

plot_data = function(df) {
  ggplot(df, aes(x, y)) + geom_point()
}
