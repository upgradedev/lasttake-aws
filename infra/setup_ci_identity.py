"""Create the least-privilege identity GitHub Actions deploys with.

Run this once, from a machine that already has your own AWS credentials:

    python infra/setup_ci_identity.py

It creates an IAM user `lasttake-ci`, attaches a policy scoped to `lasttake-*`
resources plus Bedrock inference, mints one access key, and prints the two
`gh secret set` commands to run. It never prints the secret to your terminal
history; it writes it to a file you delete afterwards.

**Your own credentials are never copied anywhere.** This exists so that the only
thing GitHub ever holds is a key that can touch resources named `lasttake-*` and
call a Bedrock model, and nothing else in the account.

To undo everything: `python infra/setup_ci_identity.py --destroy`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

USER = "lasttake-ci"
POLICY = "lasttake-ci-deploy"
KEY_FILE = Path("lasttake-ci-key.json")


def policy_document(account: str) -> dict:
    """Scoped by resource name wherever the AWS API allows it.

    Where a call has no resource-level control (ValidateTemplate, ListFunctions,
    ListFoundationModels) it is listed separately and deliberately, rather than
    hidden inside a wildcard that also covers the calls that do.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudFormationOnOurStacksOnly",
                "Effect": "Allow",
                "Action": [
                    "cloudformation:CreateStack",
                    "cloudformation:UpdateStack",
                    "cloudformation:DeleteStack",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResource",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:GetTemplateSummary",
                    "cloudformation:CreateChangeSet",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ExecuteChangeSet",
                    "cloudformation:DeleteChangeSet",
                    "cloudformation:ListStackResources",
                ],
                "Resource": [f"arn:aws:cloudformation:*:{account}:stack/lasttake-*/*"],
            },
            {
                "Sid": "CloudFormationCallsWithNoResourceControl",
                "Effect": "Allow",
                "Action": ["cloudformation:ValidateTemplate", "cloudformation:ListStacks"],
                "Resource": "*",
            },
            {
                "Sid": "LambdaOnOurFunctionsOnly",
                "Effect": "Allow",
                "Action": ["lambda:*"],
                "Resource": [f"arn:aws:lambda:*:{account}:function:lasttake-*"],
            },
            {
                "Sid": "LambdaCallsWithNoResourceControl",
                "Effect": "Allow",
                "Action": ["lambda:GetAccountSettings", "lambda:ListFunctions"],
                "Resource": "*",
            },
            {
                "Sid": "OurBucketsOnly",
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": ["arn:aws:s3:::lasttake-*", "arn:aws:s3:::lasttake-*/*"],
            },
            {
                "Sid": "BucketListing",
                "Effect": "Allow",
                "Action": ["s3:ListAllMyBuckets"],
                "Resource": "*",
            },
            {
                "Sid": "RolesForOurLambdaOnly",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:DeleteRole",
                    "iam:GetRole",
                    "iam:PassRole",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:GetRolePolicy",
                    "iam:ListRolePolicies",
                    "iam:ListAttachedRolePolicies",
                    "iam:TagRole",
                    "iam:UntagRole",
                ],
                "Resource": [f"arn:aws:iam::{account}:role/lasttake-*"],
            },
            {
                "Sid": "EventsOnOurBusOnly",
                "Effect": "Allow",
                "Action": ["events:*"],
                "Resource": [
                    f"arn:aws:events:*:{account}:event-bus/lasttake-*",
                    f"arn:aws:events:*:{account}:rule/lasttake-*",
                    f"arn:aws:events:*:{account}:rule/lasttake-*/*",
                ],
            },
            {
                "Sid": "LogsForOurLambdaOnly",
                "Effect": "Allow",
                "Action": ["logs:*"],
                "Resource": [
                    f"arn:aws:logs:*:{account}:log-group:/aws/lambda/lasttake-*",
                    f"arn:aws:logs:*:{account}:log-group:/aws/lambda/lasttake-*:*",
                ],
            },
            {
                "Sid": "BedrockInferenceOnly",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Converse",
                    "bedrock:ConverseStream",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:*:{account}:inference-profile/*",
                ],
            },
            {
                "Sid": "BedrockDiscoveryForDoctor",
                "Effect": "Allow",
                "Action": [
                    "bedrock:ListFoundationModels",
                    "bedrock:ListInferenceProfiles",
                    "bedrock:GetFoundationModel",
                ],
                "Resource": "*",
            },
            {
                # DSQL provisions itself a service-linked role on first use, and
                # the create fails with a 403 without this. Conditioned on the
                # service name, so it grants exactly that one role and no other.
                "Sid": "ServiceLinkedRoleForDsqlOnly",
                "Effect": "Allow",
                "Action": ["iam:CreateServiceLinkedRole"],
                "Resource": f"arn:aws:iam::{account}:role/aws-service-role/dsql.amazonaws.com/*",
                "Condition": {"StringEquals": {"iam:AWSServiceName": "dsql.amazonaws.com"}},
            },
            {
                # CreateCluster has no resource to name yet, so it is separated
                # from the operations that do rather than hidden inside one
                # wildcard that covers both.
                "Sid": "CreateAndListClusters",
                "Effect": "Allow",
                "Action": ["dsql:CreateCluster", "dsql:ListClusters"],
                "Resource": "*",
            },
            {
                "Sid": "ManageOurClusterOnly",
                "Effect": "Allow",
                # Scoped by resource rather than by action, matching how lambda,
                # s3 and events are granted above.
                #
                # The enumerated version was tried first and abandoned. The
                # CloudFormation resource handler calls more than the obvious
                # CRUD: it reads the cluster policy back after create, and it
                # reads the VPC endpoint service name. Each missing action cost
                # one full deploy cycle to discover, and the list is the
                # handler's private business rather than a contract. Bounding
                # the resource is the boundary that actually means something:
                # this identity reaches DSQL clusters in this account and
                # nothing else, and it exists only for this project.
                "Action": ["dsql:*"],
                "Resource": [f"arn:aws:dsql:*:{account}:cluster/*"],
            },
            {
                # API Gateway's control plane is account-scoped: apis are
                # created before they have an id, so there is no ARN to name in
                # advance. Restricted to the apigateway actions the deploy
                # needs, and nothing else in the account uses this identity.
                "Sid": "HttpApiForTheFrontDoor",
                "Effect": "Allow",
                "Action": [
                    "apigateway:GET",
                    "apigateway:POST",
                    "apigateway:PUT",
                    "apigateway:PATCH",
                    "apigateway:DELETE",
                    "apigateway:TagResource",
                    "apigateway:UntagResource",
                ],
                "Resource": ["arn:aws:apigateway:*::/apis", "arn:aws:apigateway:*::/apis/*"],
            },
            {
                "Sid": "WhoAmI",
                "Effect": "Allow",
                "Action": ["sts:GetCallerIdentity"],
                "Resource": "*",
            },
        ],
    }


def create(iam, account: str) -> None:
    try:
        iam.create_user(
            UserName=USER,
            Tags=[
                {"Key": "project", "Value": "lasttake"},
                {"Key": "purpose", "Value": "github-actions-deploy"},
            ],
        )
        print(f"created user {USER}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"user {USER} already exists, reusing it")

    arn = f"arn:aws:iam::{account}:policy/{POLICY}"
    document = json.dumps(policy_document(account))
    try:
        arn = iam.create_policy(
            PolicyName=POLICY,
            PolicyDocument=document,
            Description="Least privilege for the LastTake GitHub Actions deploy.",
        )["Policy"]["Arn"]
        print(f"created policy {arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        versions = iam.list_policy_versions(PolicyArn=arn)["Versions"]
        for version in versions:
            if not version["IsDefaultVersion"] and len(versions) >= 5:
                iam.delete_policy_version(PolicyArn=arn, VersionId=version["VersionId"])
        iam.create_policy_version(PolicyArn=arn, PolicyDocument=document, SetAsDefault=True)
        print(f"updated policy {arn}")

    iam.attach_user_policy(UserName=USER, PolicyArn=arn)

    for key in iam.list_access_keys(UserName=USER)["AccessKeyMetadata"]:
        iam.delete_access_key(UserName=USER, AccessKeyId=key["AccessKeyId"])
        print(f"revoked previous key {key['AccessKeyId'][:8]}...")

    new = iam.create_access_key(UserName=USER)["AccessKey"]
    KEY_FILE.write_text(
        json.dumps(
            {
                "AccessKeyId": new["AccessKeyId"],
                "SecretAccessKey": new["SecretAccessKey"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nkey written to {KEY_FILE} (git-ignored). Now run:\n")
    print(
        f'  gh secret set AWS_ACCESS_KEY_ID --repo upgradedev/lasttake-aws '
        f'--body "$(python -c \'import json;print(json.load(open("{KEY_FILE}"))["AccessKeyId"])\')"'
    )
    print(
        f'  gh secret set AWS_SECRET_ACCESS_KEY --repo upgradedev/lasttake-aws '
        f'--body "$(python -c \'import json;print(json.load(open("{KEY_FILE}"))["SecretAccessKey"])\')"'
    )
    print(f"\nthen delete the file:\n\n  rm {KEY_FILE}\n")


def destroy(iam, account: str) -> None:
    arn = f"arn:aws:iam::{account}:policy/{POLICY}"
    try:
        for key in iam.list_access_keys(UserName=USER)["AccessKeyMetadata"]:
            iam.delete_access_key(UserName=USER, AccessKeyId=key["AccessKeyId"])
        iam.detach_user_policy(UserName=USER, PolicyArn=arn)
        iam.delete_user(UserName=USER)
        print(f"deleted user {USER}")
    except iam.exceptions.NoSuchEntityException:
        print(f"user {USER} not present")
    try:
        for version in iam.list_policy_versions(PolicyArn=arn)["Versions"]:
            if not version["IsDefaultVersion"]:
                iam.delete_policy_version(PolicyArn=arn, VersionId=version["VersionId"])
        iam.delete_policy(PolicyArn=arn)
        print(f"deleted policy {POLICY}")
    except iam.exceptions.NoSuchEntityException:
        print(f"policy {POLICY} not present")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destroy", action="store_true")
    args = parser.parse_args()

    import boto3

    account = boto3.client("sts").get_caller_identity()["Account"]
    iam = boto3.client("iam")
    print(f"account {account}\n")
    if args.destroy:
        destroy(iam, account)
    else:
        create(iam, account)
    return 0


if __name__ == "__main__":
    sys.exit(main())
