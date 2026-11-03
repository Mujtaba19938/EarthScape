# Supporting statistics for CO2 and global temperature, using base R only.
# train_models.py writes co2_temperature.csv, so run that first.
# Open this folder in RStudio, or run:  Rscript correlation_analysis.R
#
# Pearson r should match the ML page: about 0.967 on raw values (n = 67) and
# about 0.316 on year-to-year changes (n = 66).

climate <- read.csv("co2_temperature.csv")
output <- "r_results.txt"
sink(output, split = TRUE)

cat("Years:", min(climate$year), "to", max(climate$year), "\n\n")

cat("--- Raw yearly values ---\n")
print(cor.test(climate$co2, climate$anomaly, method = "pearson"))
print(cor.test(climate$co2, climate$anomaly, method = "spearman", exact = FALSE))

cat("--- Year-to-year changes (removes the shared long-term rise) ---\n")
co2_change <- diff(climate$co2)
anomaly_change <- diff(climate$anomaly)
print(cor.test(co2_change, anomaly_change, method = "pearson"))
print(cor.test(co2_change, anomaly_change, method = "spearman", exact = FALSE))

cat("--- Straight-line fit of temperature anomaly on CO2 ---\n")
fit <- lm(anomaly ~ co2, data = climate)
print(summary(fit))
print(confint(fit))

# Durbin-Watson near 2 means leftover errors are unrelated from year to year.
# Well below 2 means the p-values above look stronger than they really are.
errors <- residuals(fit)
durbin_watson <- sum(diff(errors)^2) / sum(errors^2)
cat("Durbin-Watson:", round(durbin_watson, 3), "\n")

sink()

png("co2_temperature.png", width = 900, height = 600)
plot(climate$co2, climate$anomaly, pch = 19, col = "#1a814a",
     xlab = "Atmospheric CO2 (ppm, Mauna Loa)", ylab = "Temperature anomaly (°C, NASA GISTEMP)",
     main = "CO2 and global temperature")
abline(fit)
dev.off()

cat("Results saved to", output, "and co2_temperature.png\n")
