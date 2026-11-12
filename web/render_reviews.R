args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: Rscript render_reviews.R reviews.csv output.svg")
library(ggplot2)
library(ggdist)
font_family <- "Noto Sans CJK SC"
reviews <- read.csv(args[[1]], colClasses = c(paper_id = "character", review_id = "character"))
sample <- jsonlite::fromJSON(file.path(dirname(args[[1]]), "sample.json"))
stopifnot(!anyDuplicated(reviews$review_id), !anyDuplicated(sample$papers$paper_id))
stopifnot(all(reviews$paper_id %in% sample$papers$paper_id))
valid <- reviews[!is.na(reviews$rating), ]
if (!nrow(valid)) stop("No observed ratings in cohort")
by_paper <- split(valid$rating, valid$paper_id)
papers <- sample$papers[c("paper_id", "year", "decision")]
papers$n <- vapply(papers$paper_id, function(id) length(by_paper[[id]]), integer(1))
papers$mean <- vapply(papers$paper_id, function(id) if (length(by_paper[[id]])) mean(by_paper[[id]]) else NA_real_, numeric(1))
papers$sd <- vapply(papers$paper_id, function(id) if (length(by_paper[[id]]) >= 2) sd(by_paper[[id]]) else NA_real_, numeric(1))
papers$range <- vapply(papers$paper_id, function(id) if (length(by_paper[[id]]) >= 2) diff(range(by_paper[[id]])) else NA_real_, numeric(1))
stopifnot(sum(papers$n) == nrow(valid))

labels <- c(all = "全部决定", accepted = "录用", rejected = "拒稿")
colors <- c(all = "#526078", accepted = "#087f8c", rejected = "#c15b40")
groups <- do.call(rbind, lapply(names(labels), function(status) {
  p <- if (status == "all") papers else papers[papers$decision == status, ]
  p$status <- status
  p
}))
values <- do.call(rbind, lapply(c("mean", "sd"), function(metric) {
  p <- groups
  p$value <- p[[metric]]
  p$metric <- if (metric == "mean") "左列：论文均分" else "右列：篇内评分标准差"
  p
}))
values$metric <- factor(values$metric, levels = c("左列：论文均分", "右列：篇内评分标准差"))
values$status <- factor(values$status, levels = c("rejected", "accepted", "all"))
values$y <- as.numeric(values$status) * 3
values$year <- factor(values$year)
keys <- interaction(values$year, values$metric, values$status, drop = TRUE)
coverage <- do.call(rbind, lapply(split(values, keys), function(rows) {
  data.frame(year = rows$year[1], metric = rows$metric[1], status = rows$status[1], y = rows$y[1],
             n = sum(!is.na(rows$value)), excluded = sum(is.na(rows$value)))
}))
coverage$label <- paste0("有效 ", format(coverage$n, big.mark = ",", trim = TRUE),
                         " 篇；排除 ", coverage$excluded, " 篇")
observed <- values[!is.na(values$value), ]

p <- ggplot(observed, aes(x = value, y = y, fill = status,
                         group = interaction(year, metric, status))) +
  stat_slab(data = observed[observed$metric == "左列：论文均分", ],
            aes(y = y + 0.08), density = "histogram", breaks = seq(0, 10.25, by = 0.25),
            orientation = "horizontal", trim = FALSE, side = "top", scale = 0.28, normalize = "panels", alpha = 0.45) +
  stat_slab(data = observed[observed$metric == "右列：篇内评分标准差", ],
            aes(y = y + 0.08), density = "histogram", breaks = seq(0, 7.25, by = 0.25),
            orientation = "horizontal", trim = FALSE, side = "top", scale = 0.28, normalize = "panels", alpha = 0.45) +
  stat_dots(aes(y = y - 0.10), quantiles = 40, side = "bottom", scale = 0.20,
            orientation = "horizontal", dotsize = 0.65, binwidth = 0.13, overflow = "compress", color = NA) +
  stat_pointinterval(aes(y = y - 0.95, color = status), point_interval = median_qi,
                     .width = c(0.5, 0.9), point_color = "#14243A", show.legend = FALSE) +
  geom_text(data = coverage, aes(x = 0, y = y + 1.3, label = label),
            inherit.aes = FALSE, hjust = 0, size = 3.1, color = "#526078", family = font_family) +
  facet_grid(year ~ metric, scales = "free_x", labeller = label_value) +
  scale_y_continuous(breaks = (1:3) * 3, labels = labels[c("rejected", "accepted", "all")], expand = expansion(mult = 0)) +
  coord_cartesian(ylim = c(1.8, 10.8)) +
  scale_x_continuous(breaks = seq(0, 10, by = 1), expand = expansion(mult = c(0.015, 0.06))) +
  scale_fill_manual(values = colors) + scale_color_manual(values = colors) +
  labs(title = "论文评分水平与审稿分歧",
       subtitle = "左列看评分水平，右列看审稿一致程度；按年份分别比较。",
       x = "左列横轴：论文均分（分）　　右列横轴：篇内评分标准差（分）", y = NULL,
       caption = paste(
         "左列越靠右，论文均分越高；右列越靠右，同篇论文的审稿分歧越大。",
         "例如：[5、5、5、5]与[1、5、6、8]均分均为5，但标准差分别为0和约2.94。",
         "每组40点概括全部有效论文，每点约代表2.5%（1,000篇约25篇/点）。",
         "黑点＝中位数；粗线＝中间50%的论文范围；细线＝中间90%的论文范围。",
         "全部决定含录用、拒稿、撤稿等；各年分别阅读。区间描述样本中论文指标的分布。",
         sep = "\n")) +
  theme_minimal(base_size = 11, base_family = font_family) +
  theme(legend.position = "none", panel.grid.minor = element_blank(), panel.grid.major.y = element_blank(),
        strip.text = element_text(face = "bold", color = "#14243A"),
        plot.title = element_text(face = "bold", size = 17), plot.caption = element_text(hjust = 0, size = 9),
        panel.spacing = grid::unit(1, "lines"), plot.margin = margin(14, 14, 14, 14))
ggsave(args[[2]], p, device = svglite::svglite, width = 12, height = 10)
ggsave(sub("\\.svg$", ".png", args[[2]]), p, device = "png", type = "cairo", width = 12, height = 10, dpi = 220)
report_plot <- p +
  theme(plot.title = element_text(size = 14), plot.subtitle = element_text(size = 9),
        axis.text = element_text(size = 9.5), axis.title = element_text(size = 9),
        strip.text = element_text(size = 10), plot.caption = element_text(size = 8.5))
ggsave(sub("\\.svg$", "-report.png", args[[2]]), report_plot, device = "png", type = "cairo", width = 8.5, height = 9, dpi = 300)
write.csv(papers, file.path(dirname(args[[2]]), "paper-review-statistics.csv"), row.names = FALSE, na = "")
write.csv(coverage, file.path(dirname(args[[2]]), "review-distribution-coverage.csv"), row.names = FALSE)
cat("R:", as.character(getRversion()), "ggdist:", as.character(packageVersion("ggdist")),
    "papers:", nrow(papers), "mean:", sum(papers$n >= 1), "SD:", sum(papers$n >= 2), "valid ratings:", nrow(valid), "\n")
