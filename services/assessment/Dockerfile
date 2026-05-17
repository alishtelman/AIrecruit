FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN go build -o /out/assessment-service ./cmd/assessment-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/assessment-service /app/assessment-service

EXPOSE 8080
CMD ["/app/assessment-service"]
